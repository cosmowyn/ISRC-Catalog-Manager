import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CodeRegistryService,
)
from isrc_manager.services import (
    ContractTemplateDraftPayload,
    ContractTemplateIngestionError,
    ContractTemplateOutputArtifactPayload,
    ContractTemplatePayload,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplatePlaceholderPayload,
    ContractTemplateResolvedSnapshotPayload,
    ContractTemplateRevisionAssetPayload,
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


class AvailabilityDocxHtmlAdapter(FakeDocxHtmlAdapter):
    def __init__(self, *, available=True, html_text=None):
        super().__init__(html_text=html_text)
        self.available = available

    def is_available(self):
        return self.available


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

    def test_draft_working_file_lifecycle_keeps_paths_inside_managed_storage(self):
        template = self._create_template()
        source_path = self.root / "draft-source.docx"
        source_path.write_bytes(
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),))
        )
        revision = self.service.import_revision_from_path(
            template.template_id,
            source_path,
        ).revision
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Working Draft",
                editable_payload={"manual_values": {}, "db_selections": {}},
                storage_mode="database",
            )
        )

        self.assertIsNone(self.service.resolve_draft_working_path(draft.draft_id))
        updated = self.service.set_draft_working_file(
            draft.draft_id,
            content_bytes=b"<html><body>Initial</body></html>",
            filename="../unsafe draft.html",
            mime_type="",
        )
        generated_path = self.service.resolve_draft_working_path(draft.draft_id)
        self.assertIsNotNone(generated_path)
        assert generated_path is not None
        self.assertTrue(generated_path.exists())
        self.assertEqual(generated_path.read_bytes(), b"<html><body>Initial</body></html>")
        self.assertEqual(updated.working_filename, "unsafe_draft.html")
        self.assertEqual(updated.working_mime_type, "text/html")
        self.assertEqual(
            self.service.load_draft_working_bytes(draft.draft_id),
            b"<html><body>Initial</body></html>",
        )

        manual_path = self.service.draft_store.root_path / "manual_working" / "index.html"
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        manual_path.write_bytes(b"<html><body>Manual path</body></html>")
        updated_from_path = self.service.set_draft_working_path(
            draft.draft_id,
            working_path=manual_path,
            mime_type="",
        )
        self.assertEqual(updated_from_path.working_filename, "index.html")
        self.assertEqual(updated_from_path.working_mime_type, "text/html")
        self.assertFalse(generated_path.exists())
        self.assertEqual(
            self.service.load_draft_working_bytes(draft.draft_id),
            b"<html><body>Manual path</body></html>",
        )

        outside_path = self.root / "outside.html"
        outside_path.write_text("<html>outside</html>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must stay inside managed"):
            self.service.set_draft_working_path(draft.draft_id, working_path=outside_path)
        with self.assertRaises(FileNotFoundError):
            self.service.set_draft_working_path(
                draft.draft_id,
                working_path=self.service.draft_store.root_path / "missing.html",
            )

        cleared = self.service.clear_draft_working_file(draft.draft_id)
        self.assertIsNone(cleared.working_file_path)
        self.assertIsNone(self.service.resolve_draft_working_path(draft.draft_id))
        self.assertFalse(manual_path.exists())

    def test_draft_registry_assignments_are_unique_and_reused_for_same_symbol(self):
        template = self._create_template()
        source_path = self.root / "registry-draft.docx"
        source_path.write_bytes(
            make_docx_bytes(document_paragraphs=(("Key ", "{{db.contract.registry_sha256_key}}"),))
        )
        revision = self.service.import_revision_from_path(
            template.template_id,
            source_path,
        ).revision
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Registry Draft",
                editable_payload={},
                storage_mode="database",
            )
        )
        other_draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Other Registry Draft",
                editable_payload={},
                storage_mode="database",
            )
        )
        registry = CodeRegistryService(self.conn)
        entry = registry.generate_sha256_key(created_via="test.draft").entry
        other_entry = registry.generate_sha256_key(created_via="test.draft.other").entry

        assignment = self.service.ensure_draft_registry_assignment(
            draft.draft_id,
            canonical_symbol="{{db.contract.registry_sha256_key}}",
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            owner_kind="contract",
            registry_entry_id=entry.id,
        )
        reused = self.service.ensure_draft_registry_assignment(
            draft.draft_id,
            canonical_symbol="{{db.contract.registry_sha256_key}}",
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            owner_kind="contract",
            registry_entry_id=entry.id,
        )

        self.assertEqual(reused.assignment_id, assignment.assignment_id)
        self.assertEqual(
            self.service.fetch_draft_registry_assignment_by_id(assignment.assignment_id),
            assignment,
        )
        self.assertEqual(
            [
                item.assignment_id
                for item in self.service.list_draft_registry_assignments(draft.draft_id)
            ],
            [assignment.assignment_id],
        )
        with self.assertRaisesRegex(ValueError, "Canonical symbol is required"):
            self.service.ensure_draft_registry_assignment(
                draft.draft_id,
                canonical_symbol="",
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                owner_kind="contract",
                registry_entry_id=other_entry.id,
            )
        with self.assertRaisesRegex(ValueError, "already owns registry value"):
            self.service.ensure_draft_registry_assignment(
                draft.draft_id,
                canonical_symbol="{{db.contract.registry_sha256_key}}",
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                owner_kind="contract",
                registry_entry_id=other_entry.id,
            )
        with self.assertRaisesRegex(ValueError, "already linked to another draft"):
            self.service.ensure_draft_registry_assignment(
                other_draft.draft_id,
                canonical_symbol="{{db.contract.registry_sha256_key}}",
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                owner_kind="contract",
                registry_entry_id=entry.id,
            )

    def test_template_revision_guardrails_assets_and_bad_imports_are_rolled_back(self):
        template = self._create_template()
        missing_source = self.root / "missing-source.docx"

        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.archive_template(999_001)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.duplicate_template(999_002)
        with self.assertRaises(FileNotFoundError):
            self.service.add_revision_from_path(template.template_id, missing_source)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.replace_revision_assets(999_003, assets=())
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.set_active_revision(999_004)
        with self.assertRaises(FileNotFoundError):
            self.service.scan_source_path(missing_source)
        with self.assertRaises(FileNotFoundError):
            self.service.import_revision_from_path(template.template_id, missing_source)

        bad_package = self.root / "bad-html.zip"
        bad_package.write_bytes(b"not a zip")
        with self.assertRaises(ContractTemplateIngestionError):
            self.service.scan_source_path(bad_package, source_format="html")
        with self.assertRaises(ContractTemplateIngestionError):
            self.service.import_revision_from_bytes(
                template.template_id,
                b"not a zip",
                payload=ContractTemplateRevisionPayload(
                    source_filename="bad-html.zip",
                    source_format="html",
                ),
            )
        self.assertEqual(self.service.list_revisions(template.template_id), [])

        archived = self.service.archive_template(template.template_id, archived=True)
        duplicate = self.service.duplicate_template(template.template_id)
        self.assertTrue(archived.archived)
        self.assertTrue(duplicate.archived)
        self.assertNotIn(
            template.template_id, [item.template_id for item in self.service.list_templates()]
        )
        self.assertIn(
            template.template_id,
            [item.template_id for item in self.service.list_templates(include_archived=True)],
        )

        revision = self.service.add_revision_from_bytes(
            duplicate.template_id,
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),)),
            payload=ContractTemplateRevisionPayload(
                source_filename="asset-source.docx",
                storage_mode="database",
            ),
        )
        assets = self.service.replace_revision_assets(
            revision.revision_id,
            assets=(
                ContractTemplateRevisionAssetPayload(
                    package_rel_path="",
                    managed_file_path="",
                ),
                ContractTemplateRevisionAssetPayload(
                    package_rel_path="assets/banner.png",
                    managed_file_path="contract_template_sources/assets/banner.png",
                    source_filename="",
                    mime_type="",
                    size_bytes=-5,
                    checksum_sha256="",
                    asset_role="",
                ),
            ),
        )
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].source_filename, "banner.png")
        self.assertEqual(assets[0].mime_type, "image/png")
        self.assertEqual(assets[0].size_bytes, 0)
        self.assertEqual(assets[0].asset_role, "asset")

    def test_revision_storage_html_resolution_and_inventory_edge_paths(self):
        template = self._create_template()

        with self.assertRaises(FileNotFoundError):
            self.service.load_revision_source_bytes(999_100)
        self.assertIsNone(self.service.resolve_html_revision_source_path(999_101))
        self.assertIsNone(self.service.resolve_html_revision_bundle_root(999_102))
        self.assertFalse(self.service.revision_supports_html_working_draft(999_103))
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.ensure_html_revision_source_path(999_104)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.convert_revision_storage_mode(999_105, "database")
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.replace_revision_placeholder_inventory(999_106, placeholders=())
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.replace_placeholder_bindings(999_107, bindings=())

        with self.assertRaises(ContractTemplateIngestionError):
            self.service._scan_source_bytes(
                b"plain text",
                source_filename="contract.txt",
                source_format="txt",
            )
        self.service.pages_adapter = FakePagesAdapter(
            docx_bytes=make_docx_bytes(
                document_paragraphs=(("Track ", "{{db.track.track_title}}"),)
            )
        )
        pages_scan = self.service.scan_source_bytes(
            b"pages-source",
            source_filename="contract",
            source_format="pages",
        )
        self.assertEqual(pages_scan.scan_status, "scan_ready")
        self.service.pages_adapter = FakePagesAdapter(error_message="conversion failed")
        blocked_pages_scan = self.service.scan_source_bytes(
            b"pages-source",
            source_filename="contract.pages",
            source_format="pages",
        )
        self.assertEqual(blocked_pages_scan.scan_status, "scan_blocked")

        db_revision = self.service.add_revision_from_bytes(
            template.template_id,
            make_docx_bytes(),
            payload=ContractTemplateRevisionPayload(
                source_filename="db-source.docx",
                storage_mode="database",
            ),
        )
        with self.conn:
            self.conn.execute("DROP TRIGGER trg_contract_template_revisions_storage_upd")
            self.conn.execute(
                """
                UPDATE ContractTemplateRevisions
                SET source_blob=NULL, managed_file_path=NULL, storage_mode='database'
                WHERE id=?
                """,
                (db_revision.revision_id,),
            )
        with self.assertRaises(FileNotFoundError):
            self.service.load_revision_source_bytes(db_revision.revision_id)

        managed_revision = self.service.add_revision_from_bytes(
            template.template_id,
            make_docx_bytes(document_paragraphs=(("Artist ", "{{manual.artist_name}}"),)),
            payload=ContractTemplateRevisionPayload(
                source_filename="managed-source.docx",
                storage_mode="managed_file",
            ),
        )
        managed_path = self.service.source_store.resolve(managed_revision.managed_file_path)
        self.assertIsNotNone(managed_path)
        assert managed_path is not None
        managed_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.load_revision_source_bytes(managed_revision.revision_id)

        convertible = self.service.add_revision_from_bytes(
            template.template_id,
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),)),
            payload=ContractTemplateRevisionPayload(
                source_filename="convertible.docx",
                storage_mode="managed_file",
            ),
        )
        stale_path = self.service.source_store.resolve(convertible.managed_file_path)
        converted_to_db = self.service.convert_revision_storage_mode(
            convertible.revision_id,
            "database",
        )
        self.assertTrue(converted_to_db.stored_in_database)
        self.assertIsNotNone(stale_path)
        assert stale_path is not None
        self.assertFalse(stale_path.exists())
        self.assertEqual(
            self.service.convert_revision_storage_mode(convertible.revision_id, "database"),
            converted_to_db,
        )
        converted_to_file = self.service.convert_revision_storage_mode(
            convertible.revision_id,
            "managed_file",
        )
        converted_file_path = self.service.source_store.resolve(converted_to_file.managed_file_path)
        self.assertIsNotNone(converted_file_path)
        assert converted_file_path is not None
        self.assertTrue(converted_file_path.exists())

        html_root = self.root / "html-conversion"
        html_root.mkdir()
        html_source = html_root / "agreement.html"
        html_source.write_text(
            "<html><body>{{manual.license_date}}</body></html>", encoding="utf-8"
        )
        html_revision = self.service.import_revision_from_path(
            template.template_id,
            html_source,
            payload=ContractTemplateRevisionPayload(source_format="html"),
        ).revision
        with self.assertRaisesRegex(ValueError, "must stay in managed-file storage"):
            self.service.convert_revision_storage_mode(html_revision.revision_id, "database")
        self.assertEqual(
            self.service.convert_revision_storage_mode(html_revision.revision_id, "managed_file"),
            html_revision,
        )

        unsupported_revision = self.service.add_revision_from_bytes(
            template.template_id,
            b"plain text",
            payload=ContractTemplateRevisionPayload(
                source_filename="contract.rtf",
                source_format="rtf",
                scan_status="scan_pending",
            ),
        )
        with self.assertRaisesRegex(ContractTemplateIngestionError, "Unsupported"):
            self.service.ensure_html_revision_source_path(unsupported_revision.revision_id)

        self.service.pages_adapter = FakePagesAdapter(available=False)
        blocked_pages_revision = self.service.add_revision_from_bytes(
            template.template_id,
            b"pages-source",
            payload=ContractTemplateRevisionPayload(
                source_filename="blocked.pages",
                source_format="pages",
                scan_status="scan_pending",
            ),
        )
        with self.assertRaisesRegex(ContractTemplateIngestionError, "unavailable"):
            self.service.ensure_html_revision_source_path(blocked_pages_revision.revision_id)

        self.service.pages_adapter = FakePagesAdapter(
            available=True,
            docx_bytes=make_docx_bytes(
                document_paragraphs=(("Track ", "{{db.track.track_title}}"),)
            ),
        )
        self.service.docx_html_adapter = AvailabilityDocxHtmlAdapter(
            available=True,
            html_text="<html><body>{{db.track.track_title}}</body></html>",
        )
        pages_without_suffix = self.service.add_revision_from_bytes(
            template.template_id,
            b"pages-source",
            payload=ContractTemplateRevisionPayload(
                source_filename="pages-contract",
                source_format="pages",
                scan_status="scan_pending",
            ),
        )
        pages_html_path = self.service.ensure_html_revision_source_path(
            pages_without_suffix.revision_id
        )
        self.assertIsNotNone(pages_html_path)
        assert pages_html_path is not None
        self.assertTrue(pages_html_path.exists())

        html_primary = self.service.resolve_html_revision_source_path(html_revision.revision_id)
        self.assertIsNotNone(html_primary)
        assert html_primary is not None
        self.assertEqual(self.service.html_package_root_for_path(html_primary), html_primary.parent)
        self.assertEqual(
            self.service.html_package_root_for_path(self.root / "outside.html"),
            self.root.resolve(),
        )

        self.service.docx_html_adapter = AvailabilityDocxHtmlAdapter(available=False)
        docx_no_html = self.service.add_revision_from_bytes(
            template.template_id,
            make_docx_bytes(),
            payload=ContractTemplateRevisionPayload(
                source_filename="no-html.docx",
                storage_mode="database",
                scan_status="scan_pending",
            ),
        )
        self.assertFalse(
            self.service.revision_supports_html_working_draft(docx_no_html.revision_id)
        )
        self.service.docx_html_adapter = AvailabilityDocxHtmlAdapter(available=True)
        self.assertTrue(self.service.revision_supports_html_working_draft(docx_no_html.revision_id))

        self.service.pages_adapter = FakePagesAdapter(available=False)
        pages_revision = self.service.add_revision_from_bytes(
            template.template_id,
            b"pages-source",
            payload=ContractTemplateRevisionPayload(
                source_filename="contract.pages",
                source_format="pages",
                scan_status="scan_pending",
            ),
        )
        self.assertFalse(
            self.service.revision_supports_html_working_draft(pages_revision.revision_id)
        )
        self.service.pages_adapter = FakePagesAdapter(available=True)
        self.assertTrue(
            self.service.revision_supports_html_working_draft(pages_revision.revision_id)
        )

        with self.assertRaisesRegex(ValueError, "unknown placeholders"):
            self.service.replace_revision_placeholder_inventory(
                converted_to_file.revision_id,
                placeholders=(
                    ContractTemplatePlaceholderPayload(
                        canonical_symbol="{{manual.artist_name}}",
                    ),
                ),
                bindings=(
                    ContractTemplatePlaceholderBindingPayload(
                        canonical_symbol="{{manual.missing_symbol}}",
                        resolver_kind="manual",
                    ),
                ),
            )
        updated_inventory = self.service.replace_revision_placeholder_inventory(
            converted_to_file.revision_id,
            placeholders=(
                ContractTemplatePlaceholderPayload(
                    canonical_symbol="{{manual.artist_name}}",
                    display_label="Artist",
                    source_occurrence_count=0,
                ),
                ContractTemplatePlaceholderPayload(
                    canonical_symbol="{{manual.artist_name}}",
                    display_label=None,
                    required=False,
                    source_occurrence_count=2,
                ),
            ),
            bindings=(
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{manual.artist_name}}",
                    resolver_kind="manual",
                    widget_hint="line_edit",
                ),
            ),
        )
        placeholders = self.service.list_placeholders(updated_inventory.revision_id)
        self.assertEqual(updated_inventory.placeholder_count, 1)
        self.assertEqual(placeholders[0].source_occurrence_count, 3)

        bindings = self.service.replace_placeholder_bindings(
            converted_to_file.revision_id,
            bindings=(
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{manual.artist_name}}",
                    resolver_kind="manual",
                    resolver_target="Manual artist",
                    scope_entity_type="track",
                    scope_policy="optional",
                    widget_hint="textarea",
                ),
            ),
        )
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].widget_hint, "textarea")

    def test_draft_payload_working_file_snapshot_artifact_and_delete_edges(self):
        template = self._create_template()
        revision = self.service.add_revision_from_bytes(
            template.template_id,
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),)),
            payload=ContractTemplateRevisionPayload(
                source_filename="draft-source.docx",
                storage_mode="database",
            ),
        )
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Edge Draft",
                editable_payload={"manual_values": {"artist": "A"}},
                storage_mode="database",
            )
        )
        updatable_draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Updatable Draft",
                editable_payload={"manual_values": {"artist": "Before"}},
                storage_mode="managed_file",
                filename="../draft payload.json",
            )
        )
        stale_payload_path = self.service.draft_store.resolve(updatable_draft.managed_file_path)
        self.assertIsNotNone(stale_payload_path)
        assert stale_payload_path is not None
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.update_draft(
                999_199,
                ContractTemplateDraftPayload(
                    revision_id=revision.revision_id,
                    name="Missing",
                    editable_payload={},
                ),
            )
        updated_draft = self.service.update_draft(
            updatable_draft.draft_id,
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="",
                editable_payload={"manual_values": {"artist": "After"}},
                status="",
                storage_mode="database",
                filename="",
                mime_type="",
            ),
        )
        self.assertTrue(updated_draft.stored_in_database)
        self.assertEqual(updated_draft.name, updatable_draft.name)
        self.assertFalse(stale_payload_path.exists())
        converted_draft = self.service.convert_draft_storage_mode(
            updatable_draft.draft_id,
            "managed_file",
        )
        converted_payload_path = self.service.draft_store.resolve(converted_draft.managed_file_path)
        self.assertIsNotNone(converted_payload_path)
        assert converted_payload_path is not None
        self.assertTrue(converted_payload_path.exists())
        self.assertEqual(
            self.service.fetch_draft_payload(updatable_draft.draft_id),
            {"manual_values": {"artist": "After"}},
        )
        archived_draft = self.service.archive_draft(updatable_draft.draft_id, archived=True)
        self.assertEqual(archived_draft.status, "archived")
        self.assertNotIn(
            updatable_draft.draft_id,
            [item.draft_id for item in self.service.list_drafts(revision_id=revision.revision_id)],
        )
        self.assertIn(
            updatable_draft.draft_id,
            [
                item.draft_id
                for item in self.service.list_drafts(
                    revision_id=revision.revision_id,
                    include_archived=True,
                )
            ],
        )
        self.assertIn(
            updatable_draft.draft_id,
            [
                item.draft_id
                for item in self.service.list_template_drafts(
                    template.template_id,
                    include_archived=True,
                )
            ],
        )
        self.assertEqual(
            self.service.archive_draft(updatable_draft.draft_id, archived=False).status,
            "draft",
        )

        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.archive_draft(999_200)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.set_draft_last_resolved_snapshot(999_201, None)
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_draft_payload(999_202)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.resolve_draft_working_path(999_203)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.set_draft_working_file(
                999_204,
                content_bytes=b"<html></html>",
                filename="missing.html",
                mime_type="",
            )
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.clear_draft_working_file(999_205)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.convert_draft_storage_mode(999_206, "database")
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.delete_draft(999_207)

        self.assertEqual(
            self.service.convert_draft_storage_mode(draft.draft_id, "database"),
            draft,
        )
        with self.conn:
            self.conn.execute("DROP TRIGGER trg_contract_template_drafts_storage_upd")
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET payload_blob=NULL, managed_file_path=NULL, storage_mode='database'
                WHERE id=?
                """,
                (draft.draft_id,),
            )
        self.assertIsNone(self.service.fetch_draft_payload(draft.draft_id))

        managed_draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Managed Draft",
                editable_payload={"manual_values": {"artist": "B"}},
                storage_mode="managed_file",
            )
        )
        managed_payload_path = self.service.draft_store.resolve(managed_draft.managed_file_path)
        self.assertIsNotNone(managed_payload_path)
        assert managed_payload_path is not None
        managed_payload_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.fetch_draft_payload(managed_draft.draft_id)

        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET working_file_path='contract_template_drafts/missing-working.html'
                WHERE id=?
                """,
                (draft.draft_id,),
            )
        self.assertIsNone(self.service.resolve_draft_working_path(draft.draft_id))
        self.assertIsNone(self.service.load_draft_working_bytes(draft.draft_id))

        relative_working = self.service.draft_store.root_path / "manual_rel" / "index.html"
        relative_working.parent.mkdir(parents=True, exist_ok=True)
        relative_working.write_bytes(b"<html><body>Relative</body></html>")
        updated_working = self.service.set_draft_working_path(
            draft.draft_id,
            working_path="contract_template_drafts/manual_rel/index.html",
            mime_type="",
        )
        self.assertEqual(updated_working.working_filename, "index.html")
        self.assertEqual(updated_working.working_mime_type, "text/html")
        self.assertEqual(
            self.service.load_draft_working_bytes(draft.draft_id),
            b"<html><body>Relative</body></html>",
        )

        no_root_service = ContractTemplateService(self.conn, data_root=None)
        with self.assertRaisesRegex(ValueError, "not configured"):
            no_root_service.set_draft_working_path(
                draft.draft_id,
                working_path=relative_working,
            )

        snapshot = self.service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=draft.draft_id,
                revision_id=revision.revision_id,
                resolved_values={"artist": "A"},
                resolution_warnings=[],
                preview_payload={"html": "<p>A</p>"},
            )
        )
        self.assertEqual(
            self.service.list_resolved_snapshots(draft_id=draft.draft_id),
            [snapshot],
        )
        self.assertIn(snapshot, self.service.list_resolved_snapshots())
        self.assertIn(snapshot, self.service.list_template_resolved_snapshots(template.template_id))
        self.assertIsNone(self.service.fetch_resolved_snapshot(999_208))

        linked_draft = self.service.set_draft_last_resolved_snapshot(
            draft.draft_id,
            snapshot.snapshot_id,
        )
        self.assertEqual(linked_draft.last_resolved_snapshot_id, snapshot.snapshot_id)

        with self.assertRaisesRegex(ValueError, "path is required"):
            self.service.create_output_artifact(
                ContractTemplateOutputArtifactPayload(
                    snapshot_id=snapshot.snapshot_id,
                    artifact_type="pdf",
                    output_path="",
                )
            )
        artifact_path = self.service.artifact_store.root_path / "exports" / "agreement.pdf"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"%PDF-1.4\n")
        data_root = self.service.data_root
        self.assertIsNotNone(data_root)
        assert data_root is not None
        artifact = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path.relative_to(data_root)),
                output_filename="",
                mime_type="",
                size_bytes=-1,
                retained=False,
                status="",
            )
        )
        self.assertEqual(artifact.output_filename, "agreement.pdf")
        self.assertEqual(artifact.size_bytes, 0)
        self.assertFalse(artifact.retained)
        self.assertIn(artifact, self.service.list_output_artifacts())
        self.assertEqual(
            self.service.list_output_artifacts(snapshot_id=snapshot.snapshot_id),
            [artifact],
        )
        self.assertIn(artifact, self.service.list_template_output_artifacts(template.template_id))
        self.assertIsNone(self.service.fetch_output_artifact(999_209))
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.delete_output_artifact(999_210)

        self.service.delete_output_artifact(artifact.artifact_id, remove_file=True)
        self.assertIsNone(self.service.fetch_output_artifact(artifact.artifact_id))
        self.assertFalse(artifact_path.exists())

        artifact_path.write_bytes(b"%PDF-1.4\n")
        artifact_for_draft_delete = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path.relative_to(data_root)),
                output_filename="agreement.pdf",
                mime_type="application/pdf",
            )
        )
        self.assertIsNotNone(
            self.service.fetch_output_artifact(artifact_for_draft_delete.artifact_id)
        )
        self.service.delete_draft(
            draft.draft_id,
            remove_managed_payload=True,
            remove_output_files=True,
        )
        self.assertIsNone(self.service.fetch_draft(draft.draft_id))
        self.assertIsNone(self.service.fetch_resolved_snapshot(snapshot.snapshot_id))
        self.assertIsNone(self.service.fetch_output_artifact(artifact_for_draft_delete.artifact_id))
        self.assertFalse(artifact_path.exists())

    def test_delete_template_removes_managed_sources_drafts_and_output_artifacts(self):
        template = self.service.create_template(
            ContractTemplatePayload(
                name="Cleanup Template",
                description="Delete tree coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "delete-html"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "seal.png").write_bytes(b"seal")
        html_source = html_root / "index.html"
        html_source.write_text(
            "<html><body><img src='assets/seal.png'>{{manual.license_date}}</body></html>",
            encoding="utf-8",
        )
        imported = self.service.import_revision_from_path(
            template.template_id,
            html_source,
            payload=ContractTemplateRevisionPayload(source_format="html"),
        )
        source_path = self.service.resolve_html_revision_source_path(imported.revision.revision_id)
        self.assertIsNotNone(source_path)
        assert source_path is not None
        source_bundle_root = source_path.parent
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=imported.revision.revision_id,
                name="Cleanup Draft",
                editable_payload={"manual_values": {}},
                storage_mode="managed_file",
            )
        )
        draft_payload_path = self.service.draft_store.resolve(draft.managed_file_path)
        self.assertIsNotNone(draft_payload_path)
        assert draft_payload_path is not None
        working = self.service.set_draft_working_file(
            draft.draft_id,
            content_bytes=b"<html><body>Working</body></html>",
            filename="working.html",
            mime_type="text/html",
        )
        working_path = self.service.draft_store.resolve(working.working_file_path)
        self.assertIsNotNone(working_path)
        assert working_path is not None
        working_bundle_root = working_path.parent
        snapshot = self.service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=draft.draft_id,
                revision_id=imported.revision.revision_id,
                resolved_values={"license_date": "2026-05-26"},
            )
        )
        artifact_path = self.service.artifact_store.root_path / "cleanup" / "agreement.pdf"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"%PDF-1.4\n")
        data_root = self.service.data_root
        self.assertIsNotNone(data_root)
        assert data_root is not None
        artifact = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path.relative_to(data_root)),
            )
        )

        self.service.delete_template(
            template.template_id,
            remove_source_files=True,
            remove_draft_files=True,
            remove_output_files=True,
        )

        self.assertIsNone(self.service.fetch_template(template.template_id))
        self.assertIsNone(self.service.fetch_revision(imported.revision.revision_id))
        self.assertIsNone(self.service.fetch_draft(draft.draft_id))
        self.assertIsNone(self.service.fetch_resolved_snapshot(snapshot.snapshot_id))
        self.assertIsNone(self.service.fetch_output_artifact(artifact.artifact_id))
        self.assertFalse(source_bundle_root.exists())
        self.assertFalse(draft_payload_path.exists())
        self.assertFalse(working_bundle_root.exists())
        self.assertFalse(artifact_path.exists())
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.delete_template(template.template_id)

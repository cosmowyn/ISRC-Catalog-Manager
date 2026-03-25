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

from tests.contract_templates._support import FakePagesAdapter, make_docx_bytes


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
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(("Track ", "{{db.track.track_title}}"),),
                header_paragraphs=(("Signed ", "{{manual.license_date}}"),),
            )
        )

        result = self.service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(storage_mode="managed_file"),
        )
        placeholders = self.service.list_placeholders(result.revision.revision_id)
        template_after = self.service.fetch_template(template.template_id)

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

    def test_import_revision_rejects_unsupported_source_format_before_storing(self):
        template = self._create_template()
        source_path = self.root / "artist-agreement.txt"
        source_path.write_text("{{db.track.track_title}}", encoding="utf-8")

        with self.assertRaisesRegex(Exception, "Unsupported template source format"):
            self.service.import_revision_from_path(template.template_id, source_path)

        self.assertEqual(self.service.list_revisions(template.template_id), [])

    def test_import_pages_revision_from_bytes_uses_adapter_and_ready_rescan_preserves_bindings(self):
        template = self._create_template()
        pages_adapter = FakePagesAdapter(
            docx_bytes=make_docx_bytes(
                document_paragraphs=(("Track ", "{{db.track.track_title}}"),)
            )
        )
        self.service = ContractTemplateService(
            self.conn,
            data_root=self.root,
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

import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates import (
    ContractTemplateCatalogService,
    ContractTemplateExportError,
    ContractTemplateExportService,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
)
from isrc_manager.services import (
    ContractTemplateDraftPayload,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakePagesAdapter,
    make_docx_bytes,
)
from tests.qt_test_helpers import require_qapplication


class ContractTemplateExportServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.root)
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00601",
                track_title="Export Service Song",
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title="Export Coverage",
                release_date="2026-03-25",
                track_length_sec=221,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00602",
                track_title="Legacy Conflict Song",
                artist_name="Aeon",
                additional_artists=[],
                album_title="Export Coverage",
                release_date="2026-03-26",
                track_length_sec=225,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.catalog_service = ContractTemplateCatalogService(self.conn)
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Export Template",
                description="Phase 6 export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                ),
                header_paragraphs=(("Artist ", "{{db.track.artist_name}}"),),
            )
        )
        self.revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        self.draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Export Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "1",
                    },
                    "manual_values": {
                        "{{manual.license_date}}": "2026-03-31",
                    },
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        self.html_adapter = FakeDocxHtmlAdapter()
        self.pages_adapter = FakePagesAdapter()
        self.export_service = ContractTemplateExportService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            track_service=self.track_service,
            html_adapter=self.html_adapter,
            pages_adapter=self.pages_adapter,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_export_draft_to_pdf_creates_snapshot_and_artifacts(self):
        result = self.export_service.export_draft_to_pdf(self.draft.draft_id)

        updated_draft = self.template_service.fetch_draft(self.draft.draft_id)
        self.assertIsNotNone(updated_draft)
        self.assertEqual(updated_draft.last_resolved_snapshot_id, result.snapshot.snapshot_id)
        self.assertEqual(result.pdf_artifact.artifact_type, "pdf")
        self.assertEqual(result.resolved_docx_artifact.artifact_type, "resolved_docx")
        self.assertTrue(result.pdf_artifact.output_path.endswith(".pdf"))
        self.assertTrue(result.resolved_docx_artifact.output_path.endswith(".docx"))
        self.assertTrue(Path(result.pdf_artifact.output_path).exists())
        self.assertTrue(Path(result.resolved_docx_artifact.output_path).exists())
        self.assertTrue(Path(result.pdf_artifact.output_path).read_bytes().startswith(b"%PDF"))
        resolved_docx_bytes = Path(result.resolved_docx_artifact.output_path).read_bytes()
        self.assertEqual(
            self.template_service.docx_scanner.scan_bytes(resolved_docx_bytes).placeholders,
            (),
        )
        artifacts = self.template_service.list_output_artifacts(
            snapshot_id=result.snapshot.snapshot_id
        )
        self.assertEqual(
            [artifact.artifact_type for artifact in artifacts],
            ["pdf", "resolved_docx"],
        )
        self.assertEqual(len(self.pages_adapter.pdf_calls), 1)
        self.assertEqual(len(self.html_adapter.calls), 0)
        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.track.artist_name}}": "Cosmowyn",
                "{{db.track.track_title}}": "Export Service Song",
                "{{manual.license_date}}": "2026-03-31",
            },
        )
        self.assertEqual(
            result.snapshot.preview_payload.get("renderer"),
            "fake_pages_bridge_pdf",
        )

    def test_export_draft_to_pdf_rejects_missing_manual_values(self):
        broken = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Broken Export Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "1",
                    },
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        with self.assertRaises(ContractTemplateExportError):
            self.export_service.export_draft_to_pdf(broken.draft_id)

    def test_export_normalizes_conflicting_legacy_track_selections_to_one_scope(self):
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Legacy Conflict Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "2",
                    },
                    "manual_values": {
                        "{{manual.license_date}}": "2026-03-31",
                    },
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        resolved_pair = (
            result.snapshot.resolved_values["{{db.track.track_title}}"],
            result.snapshot.resolved_values["{{db.track.artist_name}}"],
        )
        self.assertIn(
            resolved_pair,
            {
                ("Export Service Song", "Cosmowyn"),
                ("Legacy Conflict Song", "Aeon"),
            },
        )
        self.assertTrue(
            any("conflicting saved selections" in warning for warning in result.warnings)
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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
    PartyPayload,
    PartyService,
    SettingsReadService,
    TrackCreatePayload,
    TrackService,
)
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakeHtmlPdfAdapter,
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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.track_service = TrackService(self.conn, self.root)
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00601",
                track_title="Export Service Song",
                artist_name="Moonwake",
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
                artist_name="Lyra",
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
        self.party_service = PartyService(self.conn)
        self.party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Aeonium",
                artist_name="Aeonium Official",
                company_name="Aeonium Holdings",
                email="hello@moonium.test",
                alternative_email="legal@moonium.test",
                chamber_of_commerce_number="CoC-778899",
                vat_number="PARTY-VAT",
                pro_number="PRO-778899",
                ipi_cae="PARTY-IPI",
                artist_aliases=["Aeonium Alias", "Lyra Cosmos"],
            )
        )
        self.owner_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                artist_name="Lyra Moonwake",
                company_name="Moonwake Records",
                email="hello@moonwake.test",
                country="Netherlands",
                vat_number="BTW-OWNER",
                pro_number="REL-OWNER",
                ipi_cae="IPI-OWNER",
                party_type="organization",
            )
        )
        with self.conn:
            self.conn.execute(
                "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
                (self.owner_party_id,),
            )
        self.settings_reads = SettingsReadService(self.conn)
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
        self.html_pdf_adapter = FakeHtmlPdfAdapter()
        self.pages_adapter = FakePagesAdapter()
        self.export_service = ContractTemplateExportService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            settings_reads=self.settings_reads,
            track_service=self.track_service,
            party_service=self.party_service,
            html_adapter=self.html_adapter,
            html_pdf_adapter=self.html_pdf_adapter,
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
                "{{db.track.artist_name}}": "Moonwake",
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

    def test_export_html_draft_to_pdf_uses_native_html_working_copy_and_preserves_source(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="HTML Export Template",
                description="Native HTML export coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "html-export-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "banner.png").write_bytes(b"banner-bytes")
        source_path = html_root / "agreement.html"
        original_html = (
            "<html><body><img src='assets/banner.png'><style>p{color:#205090;}</style>"
            "<p>{{manual.license_date}}</p></body></html>"
        )
        source_path.write_text(original_html, encoding="utf-8")
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="HTML Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {"{{manual.license_date}}": "2026-04-05"},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        working_path = self.export_service.synchronize_html_draft(draft.draft_id)
        self.assertTrue(working_path.exists())
        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        source_copy = self.template_service.resolve_html_revision_source_path(revision.revision_id)
        refreshed_draft = self.template_service.fetch_draft(draft.draft_id)
        self.assertIsNotNone(refreshed_draft)
        refreshed_working_path = self.template_service.resolve_draft_working_path(draft.draft_id)
        self.assertIsNotNone(refreshed_working_path)

        self.assertTrue(refreshed_working_path.exists())
        self.assertTrue((refreshed_working_path.parent / "assets" / "banner.png").exists())
        self.assertEqual(result.resolved_docx_artifact, None)
        self.assertIsNotNone(result.resolved_html_artifact)
        self.assertEqual(result.resolved_html_artifact.artifact_type, "resolved_html")
        self.assertTrue(Path(result.resolved_html_artifact.output_path).exists())
        self.assertTrue(Path(result.pdf_artifact.output_path).read_bytes().startswith(b"%PDF"))
        self.assertIn("2026-04-05", Path(result.resolved_html_artifact.output_path).read_text())
        self.assertIn("2026-04-05", refreshed_working_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "{{manual.license_date}}",
            refreshed_working_path.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(source_copy)
        self.assertEqual(source_copy.read_text(encoding="utf-8"), original_html)
        self.assertIsNotNone(refreshed_draft.working_file_path)
        self.assertEqual(result.snapshot.preview_payload.get("renderer"), "fake_html_pdf")
        self.assertEqual(result.snapshot.preview_payload.get("source_format"), "html")
        self.assertEqual(
            result.snapshot.preview_payload.get("working_copy_path"),
            str(refreshed_working_path),
        )
        self.assertEqual(len(self.html_pdf_adapter.file_calls), 1)
        self.assertEqual(len(self.html_pdf_adapter.html_calls), 0)
        self.assertEqual(len(self.pages_adapter.pdf_calls), 0)
        self.assertEqual(len(self.html_adapter.calls), 0)
        rendered_source, rendered_pdf = self.html_pdf_adapter.file_calls[0]
        self.assertEqual(rendered_source, Path(result.resolved_html_artifact.output_path))
        self.assertEqual(rendered_pdf, Path(result.pdf_artifact.output_path))

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
                ("Export Service Song", "Moonwake"),
                ("Legacy Conflict Song", "Lyra"),
            },
        )
        self.assertTrue(
            any("conflicting saved selections" in warning for warning in result.warnings)
        )

    def test_export_resolves_expanded_party_placeholders_from_one_selected_party(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Party Export Template",
                description="Expanded party export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "party-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Display ", "{{db.party.display_name}}"),
                    ("Artist ", "{{db.party.artist_name}}"),
                    ("Aliases ", "{{db.party.artist_aliases}}"),
                    ("Company ", "{{db.party.company_name}}"),
                    ("Alt Email ", "{{db.party.alternative_email}}"),
                    ("CoC ", "{{db.party.chamber_of_commerce_number}}"),
                    ("PRO ", "{{db.party.pro_number}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Party Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {
                        "{{db.party.company_name}}": str(self.party_id),
                    },
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.party.alternative_email}}": "legal@moonium.test",
                "{{db.party.artist_aliases}}": "Aeonium Alias, Lyra Cosmos",
                "{{db.party.artist_name}}": "Aeonium Official",
                "{{db.party.chamber_of_commerce_number}}": "CoC-778899",
                "{{db.party.company_name}}": "Aeonium Holdings",
                "{{db.party.display_name}}": "Aeonium",
                "{{db.party.pro_number}}": "PRO-778899",
            },
        )
        resolved_docx_bytes = Path(result.resolved_docx_artifact.output_path).read_bytes()
        self.assertEqual(
            self.template_service.docx_scanner.scan_bytes(resolved_docx_bytes).placeholders,
            (),
        )

    def test_export_resolves_owner_placeholders_from_current_owner_party_without_selection(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Export Template",
                description="Owner settings export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                    ("Owner VAT ", "{{db.owner.vat_number}}"),
                    ("Owner IPI ", "{{db.owner.ipi_cae}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.owner.email}}": "hello@moonwake.test",
                "{{db.owner.ipi_cae}}": "IPI-OWNER",
                "{{db.owner.legal_name}}": "Moonwake Records B.V.",
                "{{db.owner.vat_number}}": "BTW-OWNER",
            },
        )

    def test_export_resolves_owner_placeholders_from_linked_owner_party_without_selection(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ApplicationOwnerBinding(id, party_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET party_id=excluded.party_id
                """,
                (self.party_id,),
            )
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Linked Owner Export Template",
                description="Owner party export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "linked-owner-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Display ", "{{db.owner.display_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                    ("Owner VAT ", "{{db.owner.vat_number}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Linked Owner Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.owner.display_name}}": "Aeonium",
                "{{db.owner.email}}": "hello@moonium.test",
                "{{db.owner.legal_name}}": "Aeonium Holdings B.V.",
                "{{db.owner.vat_number}}": "PARTY-VAT",
            },
        )

    def test_export_rejects_blank_owner_placeholder_values(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Blank Export Template",
                description="Owner settings validation coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-blank-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Blank Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        with self.conn:
            self.conn.execute(
                "UPDATE Parties SET email='' WHERE id=?",
                (self.owner_party_id,),
            )

        with self.assertRaises(ContractTemplateExportError) as exc:
            self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertIn(
            "Current Owner Party",
            str(exc.exception),
        )
        self.assertIn("{{db.owner.email}}", str(exc.exception))

    def test_export_replaces_owner_placeholders_inside_docx_attributes(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Attribute Export Template",
                description="Owner attribute replacement coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-attribute-export-template.docx"
        source_path.write_bytes(self._docx_with_owner_attribute("{{db.owner.company_name}}"))
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Attribute Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        resolved_xml = self._resolved_document_xml(result.resolved_docx_artifact.output_path)

        self.assertNotIn("{{db.owner.company_name}}", resolved_xml)
        self.assertIn('owner="Moonwake Records"', resolved_xml)

    def _docx_with_owner_attribute(self, token: str) -> bytes:
        base_bytes = make_docx_bytes(document_paragraphs=(("Owner ", token),))
        output = BytesIO()
        with ZipFile(BytesIO(base_bytes)) as source_archive:
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                for part_name in source_archive.namelist():
                    payload = source_archive.read(part_name)
                    if part_name == "word/document.xml":
                        text = payload.decode("utf-8", "replace")
                        text = text.replace(
                            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
                            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:meta="urn:test-owner" meta:owner="'
                            + token
                            + '">',
                        )
                        payload = text.encode("utf-8")
                    archive.writestr(part_name, payload)
        return output.getvalue()

    @staticmethod
    def _resolved_document_xml(path: str | Path) -> str:
        with ZipFile(Path(path)) as archive:
            return archive.read("word/document.xml").decode("utf-8", "replace")


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.services import (
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)

from tests.contract_templates._support import make_docx_bytes


class ContractTemplateFormGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.schema = DatabaseSchemaService(self.conn, data_root=self.root)
        self.schema.init_db()
        self.schema.migrate_schema()

        self.track_service = TrackService(self.conn, self.root)
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00042",
                track_title="Orbit Signal",
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title="Workspace Tests",
                release_date="2026-03-17",
                track_length_sec=242,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.catalog_service = ContractTemplateCatalogService(self.conn)
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        self.form_service = ContractTemplateFormService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_template(self):
        return self.template_service.create_template(
            ContractTemplatePayload(
                name="Form Generation Template",
                description="Phase 4 fill-form coverage",
                template_family="contract",
                source_format="docx",
            )
        )

    def test_build_form_definition_collapses_repeated_symbols_and_types_manual_fields(self):
        template = self._create_template()
        source_path = self.root / "form-generation.docx"
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
                footer_paragraphs=(
                    ("Royalty share ", "{{manual.royalty_share}}"),
                    ("Exclusive ", "{{manual.is_exclusive}}"),
                    ("Notes ", "{{manual.general_notes}}"),
                ),
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)
        placeholders = self.template_service.list_placeholders(revision.revision_id)
        bindings = self.template_service.list_placeholder_bindings(revision.revision_id)

        selector_fields = {item.selector_key: item for item in definition.selector_fields}
        manual_fields = {item.canonical_symbol: item for item in definition.manual_fields}

        self.assertEqual(len(placeholders), 5)
        self.assertEqual(
            [item.canonical_symbol for item in placeholders],
            [
                "{{db.track.track_title}}",
                "{{manual.general_notes}}",
                "{{manual.is_exclusive}}",
                "{{manual.license_date}}",
                "{{manual.royalty_share}}",
            ],
        )
        self.assertEqual(len(selector_fields), 1)
        self.assertEqual(len(manual_fields), 4)
        self.assertEqual(definition.unresolved_placeholders, ())
        self.assertEqual(definition.warnings, ())

        selector = selector_fields["{{db.track.track_title}}"]
        self.assertEqual(selector.display_label, "Track Title")
        self.assertEqual(selector.scope_entity_type, "track")
        self.assertEqual(selector.scope_policy, "track_context")
        self.assertEqual(selector.widget_kind, "track_selector")
        self.assertTrue(selector.required)
        self.assertEqual(selector.placeholder_symbols, ("{{db.track.track_title}}",))
        self.assertGreaterEqual(len(selector.choices), 1)
        self.assertIn("Orbit Signal", selector.choices[0].label)

        license_date = manual_fields["{{manual.license_date}}"]
        self.assertEqual(license_date.field_type, "date")
        self.assertEqual(license_date.widget_kind, "date_input")
        self.assertEqual(license_date.placeholder_count, 2)

        royalty_share = manual_fields["{{manual.royalty_share}}"]
        self.assertEqual(royalty_share.field_type, "number")
        self.assertEqual(royalty_share.widget_kind, "number_input")

        is_exclusive = manual_fields["{{manual.is_exclusive}}"]
        self.assertEqual(is_exclusive.field_type, "boolean")
        self.assertEqual(is_exclusive.widget_kind, "checkbox")
        self.assertEqual(is_exclusive.options, ("false", "true"))

        general_notes = manual_fields["{{manual.general_notes}}"]
        self.assertEqual(general_notes.field_type, "text")
        self.assertEqual(general_notes.widget_kind, "text_input")

        binding = next(
            item for item in bindings if item.canonical_symbol == "{{db.track.track_title}}"
        )
        self.assertEqual(binding.resolver_kind, "db")
        self.assertEqual(binding.scope_entity_type, "track")
        self.assertEqual(binding.scope_policy, "track_context")
        self.assertEqual(binding.widget_hint, "track_selector")


import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.services import (
    ContractPayload,
    ContractService,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    DatabaseSchemaService,
    PartyPayload,
    PartyService,
    SettingsReadService,
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
                isrc="NL-TST-26-00042",
                track_title="Orbit Signal",
                artist_name="Moonwake",
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
        self.party_service = PartyService(self.conn)
        self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Recordings B.V.",
                artist_name="Aeonium",
                company_name="Aeonium Recordings",
                party_type="licensee",
                email="licensing@moonium.test",
                alternative_email="contracts@moonium.test",
                chamber_of_commerce_number="CoC-556677",
                pro_number="PRO-556677",
                artist_aliases=["Aeonium Official", "Aeonium Alias"],
            )
        )
        self.owner_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                artist_name="Lyra Moonwake",
                company_name="Moonwake Records",
                email="hello@moonwake.test",
                street_name="Forest Lane",
                postal_code="1234AB",
                country="Netherlands",
                vat_number="BTW-424242",
                pro_number="REL-OWNER",
                ipi_cae="IPI-OWNER",
                party_type="organization",
            )
        )
        self.contract_service = ContractService(
            self.conn,
            self.root,
            party_service=self.party_service,
        )
        self.contract_service.create_contract(
            ContractPayload(
                title="Forest License Agreement",
                contract_type="license",
                start_date="2026-03-20",
                status="draft",
            )
        )
        self.catalog_service = ContractTemplateCatalogService(self.conn)
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
                (self.owner_party_id,),
            )
        self.settings_reads = SettingsReadService(self.conn)
        self.form_service = ContractTemplateFormService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            settings_reads=self.settings_reads,
            contract_service=self.contract_service,
            party_service=self.party_service,
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

    def test_build_form_definition_groups_db_placeholders_by_entity_scope_and_types_manual_fields(
        self,
    ):
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
                    ("Artist ", "{{db.track.artist_name}}"),
                    ("Contract starts ", "{{db.contract.start_date}}"),
                    ("Licensee ", "{{db.party.display_name}}"),
                    ("Email ", "{{db.party.email}}"),
                    ("Legal ", "{{db.party.legal_name}}"),
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

        selector_fields = {item.scope_entity_type: item for item in definition.selector_fields}
        manual_fields = {item.canonical_symbol: item for item in definition.manual_fields}

        self.assertEqual(len(placeholders), 10)
        self.assertEqual(len(selector_fields), 3)
        self.assertEqual(len(manual_fields), 4)
        self.assertEqual(definition.unresolved_placeholders, ())
        self.assertEqual(definition.warnings, ())

        placeholder_symbols = {item.canonical_symbol for item in placeholders}
        self.assertEqual(
            placeholder_symbols,
            {
                "{{db.contract.start_date}}",
                "{{db.party.display_name}}",
                "{{db.party.email}}",
                "{{db.party.legal_name}}",
                "{{db.track.artist_name}}",
                "{{db.track.track_title}}",
                "{{manual.general_notes}}",
                "{{manual.is_exclusive}}",
                "{{manual.license_date}}",
                "{{manual.royalty_share}}",
            },
        )

        track_selector = selector_fields["track"]
        self.assertEqual(track_selector.display_label, "Track Selection")
        self.assertEqual(track_selector.scope_policy, "track_context")
        self.assertEqual(track_selector.widget_kind, "track_selector")
        self.assertTrue(track_selector.required)
        self.assertEqual(
            track_selector.placeholder_symbols,
            (
                "{{db.track.artist_name}}",
                "{{db.track.track_title}}",
            ),
        )
        self.assertGreaterEqual(len(track_selector.choices), 1)
        self.assertIn("Orbit Signal", track_selector.choices[0].label)

        contract_selector = selector_fields["contract"]
        self.assertEqual(contract_selector.display_label, "Contract Selection")
        self.assertEqual(
            contract_selector.placeholder_symbols,
            ("{{db.contract.start_date}}",),
        )
        self.assertGreaterEqual(len(contract_selector.choices), 1)
        self.assertIn("Forest License Agreement", contract_selector.choices[0].label)

        party_selector = selector_fields["party"]
        self.assertEqual(party_selector.display_label, "Party Selection")
        self.assertEqual(
            party_selector.placeholder_symbols,
            (
                "{{db.party.display_name}}",
                "{{db.party.email}}",
                "{{db.party.legal_name}}",
            ),
        )
        self.assertGreaterEqual(len(party_selector.choices), 1)
        self.assertIn("Aeonium", party_selector.choices[0].label)

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

    def test_party_scope_fields_use_one_selector_and_fallback_party_labels(self):
        template = self._create_template()
        source_path = self.root / "party-form-generation.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
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
        definition = self.form_service.build_form_definition(revision.revision_id)

        self.assertEqual(len(definition.selector_fields), 1)
        party_selector = definition.selector_fields[0]
        self.assertEqual(party_selector.scope_entity_type, "party")
        self.assertEqual(party_selector.widget_kind, "party_selector")
        self.assertEqual(
            party_selector.placeholder_symbols,
            (
                "{{db.party.alternative_email}}",
                "{{db.party.artist_aliases}}",
                "{{db.party.artist_name}}",
                "{{db.party.chamber_of_commerce_number}}",
                "{{db.party.company_name}}",
                "{{db.party.pro_number}}",
            ),
        )
        self.assertGreaterEqual(len(party_selector.choices), 1)
        self.assertIn("Aeonium", party_selector.choices[0].label)

    def test_owner_scope_fields_resolve_as_automatic_current_owner_party_fields(self):
        template = self._create_template()
        source_path = self.root / "owner-form-generation.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
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
        definition = self.form_service.build_form_definition(revision.revision_id)

        self.assertEqual(len(definition.auto_fields), 3)
        self.assertEqual(len(definition.selector_fields), 0)
        self.assertEqual(len(definition.manual_fields), 0)
        self.assertEqual(
            tuple(item.canonical_symbol for item in definition.auto_fields),
            (
                "{{db.owner.email}}",
                "{{db.owner.legal_name}}",
                "{{db.owner.vat_number}}",
            ),
        )
        self.assertFalse(definition.unresolved_placeholders)
        self.assertFalse(definition.warnings)

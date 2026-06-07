import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.contract_templates.models import (
    ContractTemplateCatalogEntry,
    ContractTemplatePlaceholderBindingRecord,
    ContractTemplatePlaceholderRecord,
)
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
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)

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

    def test_registry_backed_template_symbols_are_auto_resolved_for_draft_lifecycle(self):
        template = self._create_template()
        source_path = self.root / "registry-auto-form.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track Catalog ", "{{db.track.catalog_number}}"),
                    ("Contract Number ", "{{db.contract.contract_number}}"),
                    ("License Number ", "{{db.contract.license_number}}"),
                    ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
                )
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)
        auto_fields = {item.canonical_symbol: item for item in definition.auto_fields}

        self.assertEqual(len(definition.selector_fields), 0)
        self.assertEqual(
            set(auto_fields),
            {
                "{{db.track.catalog_number}}",
                "{{db.contract.contract_number}}",
                "{{db.contract.license_number}}",
                "{{db.contract.registry_sha256_key}}",
            },
        )
        self.assertEqual(auto_fields["{{db.track.catalog_number}}"].source_label, "Draft Registry")
        self.assertIn(
            "first time the draft is saved or exported",
            auto_fields["{{db.contract.contract_number}}"].description or "",
        )

    def test_symbol_catalog_exposes_invoice_and_royalty_database_symbols(self):
        entries = {
            entry.canonical_symbol: entry for entry in self.catalog_service.list_known_symbols()
        }

        invoice_number = entries["{{db.invoice.number}}"]
        invoice_party = entries["{{db.invoice.party_name}}"]
        royalty_net = entries["{{db.royalty.net_payable}}"]

        self.assertEqual(invoice_number.scope_entity_type, "invoice")
        self.assertEqual(invoice_number.scope_policy, "invoice_selection_required")
        self.assertEqual(invoice_party.display_label, "Invoice Party Name")
        self.assertEqual(royalty_net.scope_entity_type, "royalty_statement")
        self.assertEqual(royalty_net.scope_policy, "royalty_statement_selection_required")

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

    def test_current_year_and_duplicate_controls_build_expected_fill_fields(self):
        template = self._create_template()
        source_path = self.root / "runtime-control-form.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Year ", "{{current.year}}"),
                    (
                        "Block ",
                        "{{duplicate.start}}",
                        "{{page.index}}",
                        "{{page.total}}",
                        "{{custom.index}}",
                        "Body",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)
        auto_fields = {item.canonical_symbol: item for item in definition.auto_fields}
        manual_fields = {item.canonical_symbol: item for item in definition.manual_fields}

        self.assertEqual(
            set(auto_fields),
            {
                "{{current.year}}",
                "{{custom.index}}",
                "{{duplicate.start}}",
                "{{duplicate.end}}",
                "{{page.index}}",
                "{{page.total}}",
            },
        )
        self.assertEqual(auto_fields["{{current.year}}"].source_label, "Current Date")
        self.assertEqual(auto_fields["{{page.index}}"].source_label, "Page Counter")
        self.assertEqual(auto_fields["{{custom.index}}"].source_label, "Custom Counter")
        self.assertEqual(manual_fields["{{duplicate.number}}"].field_type, "number")
        self.assertEqual(manual_fields["{{duplicate.number}}"].widget_kind, "number_input")

    def test_indexed_db_symbols_build_indexed_selector_templates(self):
        template = self._create_template()
        source_path = self.root / "indexed-db-form.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    (
                        "Indexed block ",
                        "{{duplicate.start}}",
                        "{{db.index}}",
                        "{{db.track.track_title.indexed}}",
                        "{{db.track.isrc.indexed}}",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)
        auto_fields = {item.canonical_symbol: item for item in definition.auto_fields}
        manual_fields = {item.canonical_symbol: item for item in definition.manual_fields}

        self.assertIn("{{db.index}}", auto_fields)
        self.assertEqual(auto_fields["{{db.index}}"].source_label, "DB Index")
        self.assertIn("{{duplicate.number}}", manual_fields)
        self.assertEqual(len(definition.selector_fields), 0)
        self.assertEqual(len(definition.indexed_selector_fields), 1)
        indexed_selector = definition.indexed_selector_fields[0]
        self.assertEqual(indexed_selector.display_label, "Indexed Track Selection")
        self.assertEqual(indexed_selector.scope_entity_type, "track")
        self.assertEqual(
            indexed_selector.placeholder_symbols,
            (
                "{{db.track.isrc.indexed}}",
                "{{db.track.track_title.indexed}}",
            ),
        )
        self.assertGreaterEqual(len(indexed_selector.choices), 1)

    def test_indexed_manual_symbols_build_indexed_manual_templates(self):
        template = self._create_template()
        source_path = self.root / "indexed-manual-form.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    (
                        "Indexed manual block ",
                        "{{duplicate.start}}",
                        "{{manual.version.indexed}}",
                        "{{manual.explicit$bool[yes;no;maybe].indexed}}",
                        "{{manual.status$list[draft;final;signed].indexed}}",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)
        manual_fields = {item.canonical_symbol: item for item in definition.manual_fields}
        indexed_manual_fields = {
            item.canonical_symbol: item for item in definition.indexed_manual_fields
        }

        self.assertEqual(len(definition.selector_fields), 0)
        self.assertEqual(len(definition.indexed_selector_fields), 0)
        self.assertIn("{{manual.version.indexed}}", indexed_manual_fields)
        self.assertIn("{{manual.explicit$bool[yes;no;maybe].indexed}}", indexed_manual_fields)
        self.assertIn("{{manual.status$list[draft;final;signed].indexed}}", indexed_manual_fields)
        self.assertIn("{{duplicate.number}}", manual_fields)
        self.assertEqual(
            indexed_manual_fields["{{manual.version.indexed}}"].field_type,
            "text",
        )
        self.assertEqual(
            indexed_manual_fields["{{manual.explicit$bool[yes;no;maybe].indexed}}"].field_type,
            "boolean",
        )
        self.assertEqual(
            indexed_manual_fields["{{manual.explicit$bool[yes;no;maybe].indexed}}"].widget_kind,
            "boolean_options",
        )
        self.assertEqual(
            indexed_manual_fields["{{manual.explicit$bool[yes;no;maybe].indexed}}"].options,
            ("yes", "no", "maybe"),
        )
        self.assertEqual(
            indexed_manual_fields["{{manual.status$list[draft;final;signed].indexed}}"].field_type,
            "list",
        )
        self.assertEqual(
            indexed_manual_fields["{{manual.status$list[draft;final;signed].indexed}}"].options,
            ("draft", "final", "signed"),
        )

    def test_form_service_edge_helpers_cover_warnings_labels_and_missing_records(self):
        missing_revision_service = ContractTemplateFormService(
            template_service=SimpleNamespace(fetch_revision=lambda _revision_id: None),
            catalog_service=SimpleNamespace(list_known_symbols=lambda: []),
        )
        with self.assertRaisesRegex(ValueError, "revision 404 not found"):
            missing_revision_service.build_form_definition(404)

        missing_template_service = ContractTemplateFormService(
            template_service=SimpleNamespace(
                fetch_revision=lambda _revision_id: SimpleNamespace(
                    revision_id=9,
                    template_id=77,
                ),
                fetch_template=lambda _template_id: None,
            ),
            catalog_service=SimpleNamespace(list_known_symbols=lambda: []),
        )
        with self.assertRaisesRegex(ValueError, "template 77 not found"):
            missing_template_service.build_form_definition(9)

        placeholder = ContractTemplatePlaceholderRecord(
            placeholder_id=1,
            revision_id=2,
            canonical_symbol="{{db.owner.phone}}",
            binding_kind="db",
            namespace="owner",
            placeholder_key="phone",
            display_label="Owner Phone",
            inferred_field_type=None,
            required=True,
            source_occurrence_count=1,
            metadata=None,
        )
        catalog_entry = ContractTemplateCatalogEntry(
            binding_kind="db",
            namespace="owner",
            key="phone",
            canonical_symbol="{{db.owner.phone}}",
            display_label="Owner Phone",
            field_type="text",
            description=None,
            scope_entity_type="owner",
            scope_policy="owner_settings_context",
            source_table=None,
            source_column=None,
        )

        no_settings_service = ContractTemplateFormService(
            template_service=SimpleNamespace(conn=self.conn),
            catalog_service=self.catalog_service,
            settings_reads=None,
        )
        self.assertIn(
            "owner-party reads are unavailable",
            no_settings_service._auto_field_warning(
                placeholder,
                binding=None,
                catalog_entry=catalog_entry,
            ),
        )
        self.assertEqual(
            self.form_service._auto_field_warning(
                placeholder,
                binding=None,
                catalog_entry=catalog_entry,
            ),
            "Owner Phone is currently blank in Current Owner Party.",
        )
        non_owner = ContractTemplatePlaceholderRecord(
            placeholder_id=2,
            revision_id=2,
            canonical_symbol="{{db.track.track_title}}",
            binding_kind="db",
            namespace="track",
            placeholder_key="track_title",
            display_label="Track Title",
            inferred_field_type=None,
            required=True,
            source_occurrence_count=1,
            metadata=None,
        )
        self.assertIsNone(
            self.form_service._auto_field_warning(
                non_owner,
                binding=None,
                catalog_entry=None,
            )
        )

        self.assertEqual(
            self.form_service._manual_field_type("signed_date", None), ("date", "date_input")
        )
        self.assertEqual(
            self.form_service._manual_field_type("has_consent", None), ("boolean", "checkbox")
        )
        self.assertEqual(
            self.form_service._manual_field_type("royalty_amount", None), ("number", "number_input")
        )
        self.assertEqual(
            self.form_service._manual_field_type("anything", "decimal"), ("number", "number_input")
        )
        self.assertEqual(self.form_service._selector_widget_hint(""), "entity_selector")
        self.assertIsNone(self.form_service._default_scope_entity_type("unknown"))
        self.assertIsNone(self.form_service._default_scope_policy("unknown"))
        self.assertEqual(self.form_service._choices_for_entity_type("unknown"), ())

        unresolved_selector = self.form_service._selector_field(
            [
                (
                    ContractTemplatePlaceholderRecord(
                        placeholder_id=3,
                        revision_id=2,
                        canonical_symbol="{{db.unknown.value}}",
                        binding_kind="db",
                        namespace="unknown",
                        placeholder_key="value",
                        display_label=None,
                        inferred_field_type=None,
                        required=False,
                        source_occurrence_count=1,
                        metadata=None,
                    ),
                    None,
                    None,
                )
            ]
        )
        self.assertIsNone(unresolved_selector)

        indexed_asset_selector = self.form_service._selector_field(
            [
                (
                    ContractTemplatePlaceholderRecord(
                        placeholder_id=4,
                        revision_id=2,
                        canonical_symbol="{{db.asset.filename.indexed}}",
                        binding_kind="db",
                        namespace="asset",
                        placeholder_key="filename",
                        display_label=None,
                        inferred_field_type=None,
                        required=True,
                        source_occurrence_count=2,
                        metadata=None,
                    ),
                    None,
                    None,
                )
            ],
            indexed=True,
        )
        self.assertEqual(indexed_asset_selector.display_label, "Indexed Asset Selection")
        self.assertEqual(indexed_asset_selector.choices, ())

        self.assertEqual(
            self.form_service._release_label(
                SimpleNamespace(id=5, title="", primary_artist="", album_artist="")
            ),
            "Release #5",
        )
        self.assertEqual(
            self.form_service._work_label(SimpleNamespace(id=6, title="", iswc="")),
            "Work #6",
        )
        self.assertEqual(
            self.form_service._contract_label(SimpleNamespace(id=7, title="", status="")),
            "Contract #7",
        )
        self.assertEqual(
            self.form_service._party_label(
                SimpleNamespace(
                    id=8,
                    display_name="",
                    artist_name="",
                    company_name="",
                    legal_name="",
                    party_type="",
                )
            ),
            "Party #8",
        )
        self.assertEqual(
            self.form_service._right_label(
                SimpleNamespace(id=9, title="", right_type="", territory="")
            ),
            "Right #9",
        )
        self.assertEqual(
            self.form_service._asset_label(SimpleNamespace(id=10, filename="", asset_type="")),
            "Asset #10",
        )

    def test_unresolved_and_empty_selector_choices_are_reported_in_form_definition(self):
        template = self._create_template()
        source_path = self.root / "selector-warning-form.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Missing scope ", "{{db.unknown.value}}"),
                    ("Release ", "{{db.release.title}}"),
                    (
                        "Indexed asset ",
                        "{{duplicate.start}}",
                        "{{db.asset.filename.indexed}}",
                        "{{duplicate.end}}",
                        "{{duplicate.number}}",
                    ),
                )
            )
        )

        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        definition = self.form_service.build_form_definition(revision.revision_id)

        self.assertEqual(definition.unresolved_placeholders, ("{{db.unknown.value}}",))
        self.assertIn(
            "No selector mapping could be derived for {{db.unknown.value}}.",
            definition.warnings,
        )
        self.assertIn("Release Selection has no selectable records yet.", definition.warnings)
        self.assertIn(
            "Indexed Asset Selection has no selectable records yet.",
            definition.warnings,
        )
        self.assertEqual(definition.selector_fields[0].choices, ())
        self.assertEqual(definition.indexed_selector_fields[0].choices, ())

    def test_form_service_payload_binding_and_choice_fallback_branches(self):
        payload = self.form_service.build_editable_payload(
            "12",
            db_selections={"track": 1},
            manual_values={"notes": "approved"},
            manual_formats={"notes": " markdown ", "": "ignored", "blank": " "},
            type_overrides={"notes": "text"},
        )
        self.assertEqual(payload["revision_id"], 12)
        self.assertEqual(payload["db_selections"], {"track": 1})
        self.assertEqual(payload["manual_values"], {"notes": "approved"})
        self.assertEqual(payload["type_overrides"], {"notes": "text"})
        self.assertEqual(payload["manual_formats"], {"notes": " markdown "})

        owner_placeholder = ContractTemplatePlaceholderRecord(
            placeholder_id=11,
            revision_id=12,
            canonical_symbol="{{db.owner.phone}}",
            binding_kind="db",
            namespace="owner",
            placeholder_key="phone",
            display_label=None,
            inferred_field_type=None,
            required=True,
            source_occurrence_count=1,
            metadata=None,
        )
        missing_db_payload = self.form_service._db_binding_payload(
            owner_placeholder,
            catalog_entry=None,
        )
        self.assertEqual(missing_db_payload.scope_entity_type, "owner")
        self.assertEqual(missing_db_payload.scope_policy, "owner_settings_context")
        self.assertEqual(missing_db_payload.metadata, {"catalog_missing": True})

        current_binding = ContractTemplatePlaceholderBindingRecord(
            binding_id=1,
            revision_id=12,
            placeholder_id=11,
            canonical_symbol="{{db.owner.phone}}",
            resolver_kind=" ",
            resolver_target="{{db.owner.custom_phone}}",
            scope_entity_type=None,
            scope_policy="owner_settings_context",
            widget_hint="owner_phone_selector",
            validation={"field_type": "tel"},
            metadata={"catalog_label": "Owner Hotline"},
            created_at=None,
            updated_at=None,
        )
        merged = self.form_service._merged_binding_payload(
            owner_placeholder,
            catalog_entry=None,
            current=current_binding,
        )
        self.assertEqual(merged.resolver_kind, "db")
        self.assertEqual(merged.resolver_target, "{{db.owner.custom_phone}}")
        self.assertEqual(merged.scope_entity_type, "owner")
        self.assertEqual(merged.widget_hint, "owner_phone_selector")
        self.assertEqual(merged.validation, {"field_type": "tel"})
        self.assertEqual(merged.metadata, {"catalog_label": "Owner Hotline"})

        auto_field = self.form_service._auto_field(
            owner_placeholder,
            binding=current_binding,
            catalog_entry=None,
        )
        self.assertIn("Owner Hotline resolves automatically", auto_field.description)

        manual_placeholder = ContractTemplatePlaceholderRecord(
            placeholder_id=12,
            revision_id=12,
            canonical_symbol="{{manual.approved_flag}}",
            binding_kind="manual",
            namespace=None,
            placeholder_key="approved_flag",
            display_label=None,
            inferred_field_type=None,
            required=False,
            source_occurrence_count=2,
            metadata=None,
        )
        manual_binding = ContractTemplatePlaceholderBindingRecord(
            binding_id=2,
            revision_id=12,
            placeholder_id=12,
            canonical_symbol="{{manual.approved_flag}}",
            resolver_kind="manual",
            resolver_target="{{manual.approved_flag}}",
            scope_entity_type=None,
            scope_policy="manual_entry",
            widget_hint="segmented_choice",
            validation={"field_type": "choice", "options": ("yes", 0)},
            metadata=None,
            created_at=None,
            updated_at=None,
        )
        manual_field = self.form_service._manual_field(
            manual_placeholder,
            binding=manual_binding,
        )
        self.assertEqual(manual_field.field_type, "choice")
        self.assertEqual(manual_field.widget_kind, "segmented_choice")
        self.assertEqual(manual_field.options, ("yes", "0"))
        self.assertEqual(
            self.form_service._manual_field_type("anything", "date"),
            ("date", "date_input"),
        )
        self.assertEqual(
            self.form_service._manual_field_type("anything", "checkbox"),
            ("boolean", "checkbox"),
        )
        self.assertEqual(
            self.form_service._manual_field_type("approved_flag", None),
            ("boolean", "checkbox"),
        )

        self.assertEqual(self.form_service._choices_for_entity_type("release"), ())
        self.assertEqual(self.form_service._choices_for_entity_type("work"), ())
        self.assertEqual(self.form_service._choices_for_entity_type("right"), ())
        self.assertEqual(self.form_service._choices_for_entity_type("asset"), ())

        rich_choice_service = ContractTemplateFormService(
            template_service=SimpleNamespace(conn=self.conn),
            catalog_service=self.catalog_service,
            release_service=SimpleNamespace(
                list_releases=lambda: (
                    SimpleNamespace(
                        id=21,
                        title="Signal Bloom",
                        primary_artist="Moonwake",
                        album_artist="",
                    ),
                )
            ),
            work_service=SimpleNamespace(
                list_works=lambda: (SimpleNamespace(id=22, title="Orbit Sketch", iswc="T-123"),)
            ),
            rights_service=SimpleNamespace(
                list_rights=lambda: (
                    SimpleNamespace(id=23, title="Sync Right", right_type="", territory="NL"),
                )
            ),
            asset_service=SimpleNamespace(
                list_assets=lambda: (
                    SimpleNamespace(id=24, filename="stem.wav", asset_type="audio"),
                )
            ),
        )
        self.assertEqual(
            rich_choice_service._choices_for_entity_type("release")[0].label,
            "Signal Bloom - Moonwake",
        )
        self.assertEqual(
            rich_choice_service._choices_for_entity_type("work")[0].label,
            "Orbit Sketch (T-123)",
        )
        self.assertEqual(
            rich_choice_service._choices_for_entity_type("right")[0].label,
            "Sync Right [NL]",
        )
        self.assertEqual(
            rich_choice_service._choices_for_entity_type("asset")[0].label,
            "stem.wav (audio)",
        )

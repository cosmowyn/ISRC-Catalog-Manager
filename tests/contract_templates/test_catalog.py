import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contract_templates import ContractTemplateCatalogService, parse_placeholder
from isrc_manager.services import CustomFieldDefinitionService, DatabaseSchemaService


class ContractTemplateCatalogServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.custom_fields = CustomFieldDefinitionService(self.conn)
        self.custom_fields.ensure_fields(
            [
                {"name": "Mood", "field_type": "dropdown", "options": "Dark|Bright"},
                {"name": "Session Date", "field_type": "date"},
                {"name": "Waveform Preview", "field_type": "blob_audio"},
            ]
        )
        self.service = ContractTemplateCatalogService(
            self.conn,
            custom_field_definition_service=self.custom_fields,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_sections_expose_curated_db_namespaces_and_custom_fields(self):
        sections = self.service.list_sections()
        namespaces = [section.namespace for section in sections]
        symbols = {entry.canonical_symbol for section in sections for entry in section.entries}

        self.assertEqual(
            namespaces,
            ["track", "release", "work", "contract", "owner", "party", "right", "asset", "custom"],
        )
        self.assertIn("{{db.track.track_title}}", symbols)
        self.assertIn("{{db.release.title}}", symbols)
        self.assertIn("{{db.contract.signature_date}}", symbols)
        self.assertIn("{{db.owner.legal_name}}", symbols)
        self.assertTrue(any(symbol.startswith("{{db.custom.cf_") for symbol in symbols))
        self.assertFalse(
            any(
                "Waveform Preview" == entry.label
                for section in sections
                for entry in section.entries
            )
        )

    def test_entries_are_filterable_by_namespace_and_search_text(self):
        contract_entries = self.service.list_entries(namespace="contract", search_text="signature")
        custom_entries = self.service.list_entries(namespace="custom", search_text="mood")
        track_entries = self.service.list_entries(namespace="track", search_text="track title")

        self.assertEqual(
            [entry.canonical_symbol for entry in contract_entries],
            ["{{db.contract.signature_date}}"],
        )
        self.assertEqual(len(custom_entries), 1)
        self.assertEqual(custom_entries[0].label, "Mood")
        self.assertEqual(custom_entries[0].field_type, "dropdown")
        self.assertEqual(custom_entries[0].options, ("Dark", "Bright"))
        self.assertEqual(len(track_entries), 1)
        self.assertEqual(track_entries[0].canonical_symbol, "{{db.track.track_title}}")
        self.assertEqual(track_entries[0].scope_entity_type, "track")
        self.assertEqual(track_entries[0].scope_policy, "track_context")
        self.assertEqual(track_entries[0].field_type, "text")

    def test_party_namespace_exposes_expanded_authoritative_identity_fields(self):
        party_entries = {entry.key: entry for entry in self.service.list_entries(namespace="party")}

        expected_keys = {
            "artist_name",
            "artist_aliases",
            "company_name",
            "first_name",
            "middle_name",
            "last_name",
            "alternative_email",
            "street_name",
            "street_number",
            "bank_account_number",
            "chamber_of_commerce_number",
            "pro_number",
        }
        self.assertTrue(expected_keys <= set(party_entries))
        self.assertEqual(
            party_entries["artist_aliases"].canonical_symbol,
            "{{db.party.artist_aliases}}",
        )
        self.assertEqual(party_entries["artist_aliases"].scope_entity_type, "party")
        self.assertEqual(party_entries["artist_aliases"].scope_policy, "party_selection_required")
        self.assertEqual(party_entries["bank_account_number"].field_type, "text")

    def test_owner_namespace_exposes_current_owner_party_symbols(self):
        owner_entries = {entry.key: entry for entry in self.service.list_entries(namespace="owner")}

        expected_keys = {
            "display_name",
            "legal_name",
            "artist_name",
            "company_name",
            "first_name",
            "last_name",
            "email",
            "alternative_email",
            "street_name",
            "postal_code",
            "country",
            "bank_account_number",
            "vat_number",
            "pro_number",
            "ipi_cae",
        }
        self.assertTrue(expected_keys <= set(owner_entries))
        self.assertEqual(
            owner_entries["legal_name"].canonical_symbol,
            "{{db.owner.legal_name}}",
        )
        self.assertEqual(owner_entries["legal_name"].scope_entity_type, "owner")
        self.assertEqual(owner_entries["legal_name"].scope_policy, "owner_settings_context")
        self.assertEqual(owner_entries["legal_name"].source_kind, "Owner Party")

    def test_all_generated_symbols_round_trip_through_canonical_parser(self):
        for entry in self.service.list_entries():
            token = parse_placeholder(entry.canonical_symbol)
            self.assertEqual(token.binding_kind, "db")
            self.assertEqual(token.namespace, entry.namespace)
            self.assertEqual(token.key, entry.key)

    def test_manual_symbol_helper_normalizes_human_labels(self):
        self.assertEqual(
            self.service.build_manual_symbol("License Date"),
            "{{manual.license_date}}",
        )
        self.assertEqual(
            self.service.build_manual_symbol("  Counterparty Name  "),
            "{{manual.counterparty_name}}",
        )

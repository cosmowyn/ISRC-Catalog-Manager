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
            ["track", "release", "work", "contract", "party", "right", "asset", "custom"],
        )
        self.assertIn("{{db.track.track_title}}", symbols)
        self.assertIn("{{db.release.title}}", symbols)
        self.assertIn("{{db.contract.signature_date}}", symbols)
        self.assertTrue(any(symbol.startswith("{{db.custom.cf_") for symbol in symbols))
        self.assertFalse(any("Waveform Preview" == entry.label for section in sections for entry in section.entries))

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

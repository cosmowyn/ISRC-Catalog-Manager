import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CATALOG_MODE_EXTERNAL,
    CodeRegistryCategoryPayload,
    CodeRegistryService,
)
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.parties import PartyService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService


class CodeRegistryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.registry = CodeRegistryService(self.conn)
        self.track_service = TrackService(self.conn, self.root)
        self.party_service = PartyService(self.conn)
        self.contract_service = ContractService(
            self.conn,
            self.root,
            party_service=self.party_service,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _set_prefix(self, system_key: str, prefix: str) -> None:
        category = self.registry.fetch_category_by_system_key(system_key)
        self.assertIsNotNone(category)
        assert category is not None
        self.registry.update_category(category.id, prefix=prefix)

    def _create_track(self, *, isrc: str, title: str) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Registry Artist",
                additional_artists=[],
                album_title="Registry Album",
                release_date="2026-04-07",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )

    def test_builtin_categories_and_custom_categories_are_available(self):
        builtin_keys = {item.system_key for item in self.registry.list_categories()}
        self.assertEqual(
            builtin_keys,
            {
                BUILTIN_CATEGORY_CATALOG_NUMBER,
                BUILTIN_CATEGORY_CONTRACT_NUMBER,
                BUILTIN_CATEGORY_LICENSE_NUMBER,
                BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            },
        )

        category_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Cue Sheet Batch",
                subject_kind="generic",
                generation_strategy="manual",
                prefix=None,
                active_flag=True,
                sort_order=99,
            )
        )
        created = self.registry.fetch_category(category_id)
        self.assertIsNotNone(created)
        assert created is not None
        self.assertEqual(created.display_name, "Cue Sheet Batch")
        self.assertIsNone(created.system_key)

    def test_builtin_category_prefix_update_allows_unchanged_label(self):
        category = self.registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        self.assertIsNotNone(category)
        assert category is not None

        updated = self.registry.update_category(
            category.id,
            display_name=category.display_name,
            prefix="ACR",
        )

        self.assertEqual(updated.display_name, "Catalog Number")
        self.assertEqual(updated.prefix, "ACR")

    def test_custom_category_can_be_deleted_when_unused(self):
        category_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Delete Me",
                subject_kind="generic",
                generation_strategy="manual",
                prefix=None,
                active_flag=True,
            )
        )

        self.registry.delete_category(category_id)

        self.assertIsNone(self.registry.fetch_category(category_id))

    def test_custom_category_with_entries_cannot_be_deleted(self):
        category_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Issued Batch",
                subject_kind="generic",
                generation_strategy="sequential",
                prefix="CUE",
                active_flag=True,
            )
        )
        self.registry.generate_next_code(category_id=category_id, created_via="test.generate")

        with self.assertRaises(ValueError) as exc_info:
            self.registry.delete_category(category_id)

        self.assertIn("immutable registry entries", str(exc_info.exception))

    def test_catalog_generation_advances_monotonically_past_imported_gaps(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        yy = datetime.now().year % 100

        first = self.registry.create_or_capture_catalog_entry(
            f"ACR{yy:02d}0001",
            created_via="test.import",
            entry_kind="imported",
        )
        gap = self.registry.create_or_capture_catalog_entry(
            f"ACR{yy:02d}0005",
            created_via="test.import",
            entry_kind="imported",
        )
        generated = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.generate",
        )

        self.assertEqual(first.sequence_number, 1)
        self.assertEqual(gap.sequence_number, 5)
        self.assertEqual(generated.entry.value, f"ACR{yy:02d}0006")
        self.assertEqual(generated.entry.sequence_number, 6)

    def test_internal_entries_are_immutable(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.generate",
        ).entry

        with self.assertRaises(sqlite3.DatabaseError) as exc_info:
            self.conn.execute(
                "UPDATE CodeRegistryEntries SET value=? WHERE id=?",
                ("MUTATED", entry.id),
            )
            self.conn.commit()

        self.assertIn("immutable", str(exc_info.exception).lower())

    def test_registry_sha256_keys_are_unique_and_distinct(self):
        first = self.registry.generate_sha256_key(created_via="test.generate").entry
        second = self.registry.generate_sha256_key(created_via="test.generate").entry

        self.assertEqual(first.category_system_key, BUILTIN_CATEGORY_REGISTRY_SHA256_KEY)
        self.assertEqual(second.category_system_key, BUILTIN_CATEGORY_REGISTRY_SHA256_KEY)
        self.assertEqual(len(first.value), 64)
        self.assertEqual(len(second.value), 64)
        self.assertRegex(first.value, r"^[0-9a-f]{64}$")
        self.assertRegex(second.value, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first.value, second.value)
        self.assertEqual(first.category_display_name, "Registry SHA-256 Key")

    def test_unused_registry_sha256_key_can_be_deleted(self):
        entry = self.registry.generate_sha256_key(created_via="test.generate").entry

        self.registry.delete_entry(entry.id)

        self.assertIsNone(self.registry.fetch_entry(entry.id))

    def test_used_registry_sha256_key_cannot_be_deleted(self):
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Linked Hash Contract",
                contract_type="license",
                status="draft",
            )
        )
        entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            created_via="test.generate",
        )

        with self.assertRaises(ValueError) as exc_info:
            self.registry.delete_entry(entry.id)

        self.assertIn("not linked to any contract", str(exc_info.exception))

    def test_external_catalog_rows_can_be_reclassified_after_prefix_setup(self):
        track_id = self._create_track(isrc="NL-TST-26-40001", title="Canonical Candidate")
        yy = datetime.now().year % 100
        canonical_value = f"ACR{yy:02d}0009"
        resolution = self.registry.resolve_catalog_input(
            mode=CATALOG_MODE_EXTERNAL,
            value=canonical_value,
            created_via="test.external",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=track_id,
            resolution=resolution,
            provenance_kind="imported",
            source_label="test.external",
        )

        before = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id, external_catalog_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(before, (canonical_value, None, 1))

        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        result = self.registry.reclassify_external_catalog_identifiers()
        after = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id, external_catalog_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        external = self.registry.fetch_external_catalog_identifier(1)

        self.assertEqual(result["promoted"], 1)
        self.assertIsNotNone(after[1])
        self.assertIsNone(after[2])
        self.assertEqual(after[0], canonical_value)
        self.assertIsNotNone(external)
        assert external is not None
        self.assertEqual(external.classification_status, "promoted")

    def test_external_catalog_values_are_shared_with_usage_count(self):
        first_track_id = self._create_track(isrc="NL-TST-26-40011", title="Album Track One")
        second_track_id = self._create_track(isrc="NL-TST-26-40012", title="Album Track Two")
        shared_value = "ALB-2501"
        resolution = self.registry.resolve_catalog_input(
            mode=CATALOG_MODE_EXTERNAL,
            value=shared_value,
            created_via="test.external.shared",
        )

        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=first_track_id,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.external.shared",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=second_track_id,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.external.shared",
        )

        first_row = self.conn.execute(
            "SELECT external_catalog_identifier_id FROM Tracks WHERE id=?",
            (first_track_id,),
        ).fetchone()
        second_row = self.conn.execute(
            "SELECT external_catalog_identifier_id FROM Tracks WHERE id=?",
            (second_track_id,),
        ).fetchone()
        self.assertIsNotNone(first_row)
        self.assertIsNotNone(second_row)
        self.assertEqual(first_row[0], second_row[0])

        records = self.registry.list_external_catalog_identifiers()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].value, shared_value)
        self.assertEqual(records[0].usage_count, 2)

    def test_external_catalog_suggestions_include_legacy_release_catalog_text(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO Releases(title, release_type, upc, catalog_number)
                VALUES (?, ?, ?, ?)
                """,
                ("Legacy Release", "album", "8720892724990", "CAT-REL-900"),
            )

        suggestions = self.registry.external_catalog_suggestions()

        self.assertIn("CAT-REL-900", suggestions)

    def test_generated_internal_entry_can_be_linked_from_workspace_service(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        track_id = self._create_track(isrc="NL-TST-26-40021", title="Link Target")
        entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.generate",
        ).entry

        self.registry.assign_entry_to_owner(entry.id, owner_kind="track", owner_id=track_id)

        row = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id, external_catalog_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(row, (entry.value, entry.id, None))
        usage = self.registry.usage_for_entry(entry.id)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0].subject_kind, "track")

    def test_contract_service_generates_and_assigns_registry_values(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Registry Contract",
                contract_type="license",
                status="draft",
            )
        )

        contract_entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.generate",
        )
        license_entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
            created_via="test.generate",
        )
        hash_entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            created_via="test.generate",
        )
        record = self.contract_service.fetch_contract(contract_id)

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.contract_registry_entry_id, contract_entry.id)
        self.assertEqual(record.license_registry_entry_id, license_entry.id)
        self.assertEqual(record.registry_sha256_key_entry_id, hash_entry.id)
        self.assertEqual(record.contract_number, contract_entry.value)
        self.assertEqual(record.license_number, license_entry.value)
        self.assertEqual(record.registry_sha256_key, hash_entry.value)
        self.assertTrue(contract_entry.value.startswith("CTR"))
        self.assertTrue(license_entry.value.startswith("LIC"))
        self.assertRegex(hash_entry.value, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

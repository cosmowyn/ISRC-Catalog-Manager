import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
    BUILTIN_CATEGORY_INVOICE_NUMBER,
    BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
    CLASSIFICATION_INTERNAL,
    CodeIdentifierClassification,
    CodeIdentifierResolution,
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

    def _create_contract(self, *, title: str) -> int:
        return self.contract_service.create_contract(
            ContractPayload(
                title=title,
                contract_type="license",
                status="draft",
            )
        )

    def test_builtin_categories_and_custom_categories_are_available(self):
        builtin_keys = {item.system_key for item in self.registry.list_categories()}
        self.assertEqual(
            builtin_keys,
            {
                BUILTIN_CATEGORY_CATALOG_NUMBER,
                BUILTIN_CATEGORY_CONTRACT_NUMBER,
                BUILTIN_CATEGORY_CREDIT_NOTE_NUMBER,
                BUILTIN_CATEGORY_INVOICE_NUMBER,
                BUILTIN_CATEGORY_LEDGER_TRANSACTION_NUMBER,
                BUILTIN_CATEGORY_LICENSE_NUMBER,
                BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                BUILTIN_CATEGORY_ROYALTY_STATEMENT_NUMBER,
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
        contract_id = self._create_contract(title="Linked Hash Contract")
        entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            created_via="test.generate",
        )

        with self.assertRaises(ValueError) as exc_info:
            self.registry.delete_entry(entry.id)

        self.assertIn("not linked to any record", str(exc_info.exception))

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
            SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
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
            SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
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
        self.assertEqual(external.classification_status, "shadowed_by_internal")

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
            "SELECT catalog_external_code_identifier_id FROM Tracks WHERE id=?",
            (first_track_id,),
        ).fetchone()
        second_row = self.conn.execute(
            "SELECT catalog_external_code_identifier_id FROM Tracks WHERE id=?",
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
            SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(row, (entry.value, entry.id, None))
        usage = self.registry.usage_for_entry(entry.id)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0].subject_kind, "track")

    def test_assignment_targets_include_tracks_releases_and_contracts_with_search(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        catalog_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.targets",
        ).entry
        track_id = self._create_track(isrc="NL-TST-26-40031", title="Registry Target Track")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO Releases(title, release_type, primary_artist, catalog_number)
                VALUES (?, ?, ?, ?)
                """,
                ("Registry Target Release", "album", "Registry Artist", "CAT-REL"),
            )
        release_id = self.conn.execute("SELECT id FROM Releases").fetchone()[0]

        all_targets = self.registry.list_assignment_targets_for_entry(
            catalog_entry.id,
            search_text="Registry Target",
        )
        track_targets = self.registry.list_assignment_targets_for_entry(
            catalog_entry.id,
            owner_kind="track",
            search_text="40031",
        )
        release_targets = self.registry.list_assignment_targets_for_entry(
            catalog_entry.id,
            owner_kind="release",
            search_text="Target Release",
        )

        self.assertEqual(
            {(target.owner_kind, target.owner_id) for target in all_targets},
            {("track", track_id), ("release", release_id)},
        )
        self.assertEqual(
            [(target.owner_kind, target.owner_id) for target in track_targets],
            [("track", track_id)],
        )
        self.assertEqual(
            [(target.owner_kind, target.owner_id) for target in release_targets],
            [("release", release_id)],
        )

        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        contract_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.targets",
        ).entry
        contract_id = self._create_contract(title="Registry Target Contract")
        contract_targets = self.registry.list_assignment_targets_for_entry(
            contract_entry.id,
            search_text="Target Contract",
        )

        self.assertEqual(
            [(target.owner_kind, target.owner_id) for target in contract_targets],
            [("contract", contract_id)],
        )
        self.assertEqual(self.registry.list_assignment_targets_for_entry(999999), [])

    def test_assign_entry_to_contract_rejects_missing_wrong_owner_and_busy_destination(self):
        with self.assertRaisesRegex(ValueError, "Registry entry 999999 was not found"):
            self.registry.assign_entry_to_owner(999999, owner_kind="contract", owner_id=1)

        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        first_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.assign",
        ).entry
        second_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.assign",
        ).entry
        contract_id = self._create_contract(title="Contract Assignment Target")

        with self.assertRaisesRegex(ValueError, "cannot be linked to that owner type"):
            self.registry.assign_entry_to_owner(
                first_entry.id,
                owner_kind="track",
                owner_id=contract_id,
            )
        with self.assertRaisesRegex(ValueError, "Contract #999999 was not found"):
            self.registry.assign_entry_to_owner(
                first_entry.id,
                owner_kind="contract",
                owner_id=999999,
            )

        self.registry.assign_entry_to_owner(
            first_entry.id,
            owner_kind="contract",
            owner_id=contract_id,
        )
        with self.assertRaisesRegex(ValueError, "Use explicit realignment"):
            self.registry.assign_entry_to_owner(
                second_entry.id,
                owner_kind="contract",
                owner_id=contract_id,
            )

        contract = self.contract_service.fetch_contract(contract_id)
        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.contract_registry_entry_id, first_entry.id)
        self.assertEqual(contract.contract_number, first_entry.value)

    def test_ensure_catalog_value_for_owner_generates_captures_and_preserves_external_values(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        track_id = self._create_track(isrc="NL-TST-26-40041", title="Needs Catalog")

        self.assertIsNone(
            self.registry.ensure_catalog_value_for_owner(
                owner_kind="track",
                owner_id=track_id,
                generate_if_missing=False,
            )
        )
        generated_value = self.registry.ensure_catalog_value_for_owner(
            owner_kind="track",
            owner_id=track_id,
            created_via="test.ensure",
        )
        generated_row = self.conn.execute(
            """
            SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
            FROM Tracks
            WHERE id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertEqual(generated_row[0], generated_value)
        self.assertIsNotNone(generated_row[1])
        self.assertIsNone(generated_row[2])

        self.conn.execute(
            "UPDATE Tracks SET catalog_number='STALE-CATALOG' WHERE id=?", (track_id,)
        )
        self.assertEqual(
            self.registry.ensure_catalog_value_for_owner(
                owner_kind="track",
                owner_id=track_id,
                created_via="test.ensure",
            ),
            generated_value,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT catalog_number FROM Tracks WHERE id=?",
                (track_id,),
            ).fetchone()[0],
            generated_value,
        )

        external_text_track = self._create_track(
            isrc="NL-TST-26-40042",
            title="External Text Catalog",
        )
        self.conn.execute(
            "UPDATE Tracks SET catalog_number='IMPORT-CAT-42' WHERE id=?",
            (external_text_track,),
        )
        self.assertEqual(
            self.registry.ensure_catalog_value_for_owner(
                owner_kind="track",
                owner_id=external_text_track,
                created_via="test.ensure",
            ),
            "IMPORT-CAT-42",
        )

        external_id_track = self._create_track(
            isrc="NL-TST-26-40043",
            title="External Identifier Catalog",
        )
        resolution = self.registry.resolve_catalog_input(
            mode=CATALOG_MODE_EXTERNAL,
            value="EXT-CAT-43",
            created_via="test.ensure.external",
        )
        self.registry.assign_catalog_to_owner(
            owner_kind="track",
            owner_id=external_id_track,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.ensure.external",
        )
        self.conn.execute(
            "UPDATE Tracks SET catalog_number='' WHERE id=?",
            (external_id_track,),
        )
        self.assertEqual(
            self.registry.ensure_catalog_value_for_owner(
                owner_kind="track",
                owner_id=external_id_track,
                created_via="test.ensure",
            ),
            "EXT-CAT-43",
        )

        with self.assertRaisesRegex(ValueError, "Unsupported catalog owner kind"):
            self.registry.ensure_catalog_value_for_owner(owner_kind="contract", owner_id=1)
        with self.assertRaisesRegex(ValueError, "Track #999999 was not found"):
            self.registry.ensure_catalog_value_for_owner(owner_kind="track", owner_id=999999)

    def test_contract_service_generates_and_assigns_registry_values(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        contract_id = self._create_contract(title="Registry Contract")

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

    def test_generation_unavailable_reason_requires_prefix_for_sequential_categories(self):
        reason = self.registry.generation_unavailable_reason(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER
        )

        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("Configure a prefix/namespace", reason)

    def test_deleting_non_highest_sequence_does_not_reuse_lower_gap(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")

        first = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry
        middle = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry
        highest = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry

        self.registry.delete_entry(middle.id)
        generated = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry

        self.assertEqual(first.sequence_number, 1)
        self.assertEqual(highest.sequence_number, 3)
        self.assertEqual(generated.sequence_number, 4)

    def test_deleting_highest_sequence_reuses_that_highest_slot(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")

        first = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry
        second = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry
        highest = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry

        self.registry.delete_entry(highest.id)
        regenerated = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.sequence",
        ).entry

        self.assertEqual(first.sequence_number, 1)
        self.assertEqual(second.sequence_number, 2)
        self.assertEqual(regenerated.sequence_number, 3)
        self.assertEqual(regenerated.value, highest.value)

    def test_unused_sequential_entry_can_be_deleted(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.delete",
        ).entry

        self.registry.delete_entry(entry.id)

        self.assertIsNone(self.registry.fetch_entry(entry.id))

    def test_linked_sequential_entry_cannot_be_deleted(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        contract_id = self._create_contract(title="Protected Contract Number")
        entry = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.generate",
        )

        with self.assertRaises(ValueError) as exc_info:
            self.registry.delete_entry(entry.id)

        self.assertIn("not linked to any record", str(exc_info.exception))

    def test_contract_registry_value_can_be_realigned_between_contracts(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        first_contract_id = self._create_contract(title="Original Contract")
        second_contract_id = self._create_contract(title="Replacement Contract")
        entry = self.contract_service.generate_registry_value_for_contract(
            first_contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.realign",
        )

        self.registry.reassign_entry_to_owner(
            entry.id,
            owner_kind="contract",
            owner_id=second_contract_id,
        )

        first_contract = self.contract_service.fetch_contract(first_contract_id)
        second_contract = self.contract_service.fetch_contract(second_contract_id)
        self.assertIsNotNone(first_contract)
        self.assertIsNotNone(second_contract)
        assert first_contract is not None
        assert second_contract is not None
        self.assertIsNone(first_contract.contract_registry_entry_id)
        self.assertIsNone(first_contract.contract_number)
        self.assertEqual(second_contract.contract_registry_entry_id, entry.id)
        self.assertEqual(second_contract.contract_number, entry.value)

    def test_contract_registry_realign_rejects_destination_conflict(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        first_contract_id = self._create_contract(title="First Contract")
        second_contract_id = self._create_contract(title="Second Contract")
        entry = self.contract_service.generate_registry_value_for_contract(
            first_contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.realign",
        )
        other_entry = self.contract_service.generate_registry_value_for_contract(
            second_contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.realign",
        )

        with self.assertRaises(ValueError) as exc_info:
            self.registry.reassign_entry_to_owner(
                entry.id,
                owner_kind="contract",
                owner_id=second_contract_id,
            )

        self.assertIn(other_entry.value, str(exc_info.exception))

    def test_ensure_registry_value_for_contract_reuses_existing_link(self):
        self._set_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        contract_id = self._create_contract(title="Existing License Contract")
        generated = self.contract_service.generate_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
            created_via="test.generate",
        )
        count_before = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]

        ensured = self.contract_service.ensure_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
            created_via="test.ensure",
        )
        count_after = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]

        self.assertEqual(ensured.id, generated.id)
        self.assertEqual(count_after, count_before)

    def test_ensure_registry_value_for_contract_captures_existing_valid_text(self):
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        yy = datetime.now().year % 100
        contract_id = self._create_contract(title="Captured Contract Number")
        raw_value = f"CTR{yy:02d}0042"
        with self.conn:
            self.conn.execute(
                """
                UPDATE Contracts
                SET contract_number=?,
                    contract_registry_entry_id=NULL
                WHERE id=?
                """,
                (raw_value, contract_id),
            )

        entry = self.contract_service.ensure_registry_value_for_contract(
            contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.capture",
        )
        contract = self.contract_service.fetch_contract(contract_id)

        self.assertEqual(entry.value, raw_value)
        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.contract_number, raw_value)
        self.assertEqual(contract.contract_registry_entry_id, entry.id)

    def test_identifier_classification_edges_for_prefix_sha_and_unknown_category(self):
        unknown = self.registry.classify_identifier_value(
            system_key="missing.category",
            value="External Value",
        )
        self.assertEqual(unknown.classification, CATALOG_MODE_EXTERNAL)
        self.assertEqual(unknown.reason, "The requested identifier category is not configured.")

        blank = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value="",
        )
        self.assertEqual(blank.classification, CATALOG_MODE_EMPTY)

        no_prefix_candidate = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value="ABC260001",
        )
        self.assertEqual(no_prefix_candidate.classification, "canonical_candidate")
        no_prefix_external = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value="album import value",
        )
        self.assertEqual(no_prefix_external.classification, CATALOG_MODE_EXTERNAL)

        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        yy = datetime.now().year % 100
        malformed = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=f"ACR{yy:02d}ABCD",
        )
        self.assertEqual(malformed.classification, "mismatch")
        out_of_range = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=f"ACR{yy:02d}0000",
        )
        self.assertEqual(out_of_range.classification, "mismatch")

        canonical_value = f"ACR{yy:02d}0042"
        internal = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=canonical_value,
        )
        self.assertEqual(internal.classification, CATALOG_MODE_INTERNAL)
        captured = self.registry.capture_value_for_category(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=canonical_value,
            created_via="test.classify",
            entry_kind="manual_capture",
        )
        matched = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=canonical_value,
        )
        self.assertEqual(matched.existing_entry_id, captured.id)

        sha_entry = self.registry.generate_sha256_key(created_via="test.sha").entry
        sha_external = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            value=sha_entry.value,
            allow_existing_internal_match=False,
        )
        self.assertEqual(sha_external.classification, CATALOG_MODE_EXTERNAL)
        sha_internal = self.registry.classify_identifier_value(
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            value=sha_entry.value,
            allow_existing_internal_match=True,
        )
        self.assertEqual(sha_internal.classification, CATALOG_MODE_EXTERNAL)
        self.assertIn("remain external", sha_internal.reason)

    def test_category_update_validation_and_generation_unavailable_edges(self):
        category_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Sequential One",
                subject_kind="generic",
                generation_strategy="sequential",
                prefix="SEQ",
                active_flag=True,
            )
        )
        other_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Sequential Two",
                subject_kind="generic",
                generation_strategy="sequential",
                prefix="ALT",
                active_flag=True,
            )
        )

        with self.assertRaises(ValueError) as exc_info:
            self.registry.update_category(other_id, prefix="SEQX")
        self.assertIn("conflicts", str(exc_info.exception))

        updated = self.registry.update_category(category_id, active_flag=False)
        self.assertFalse(updated.active_flag)
        self.assertIn(
            "inactive",
            self.registry.generation_unavailable_reason(category_id=category_id),
        )

        builtin = self.registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
        self.assertIsNotNone(builtin)
        assert builtin is not None
        with self.assertRaises(ValueError):
            self.registry.update_category(builtin.id, display_name="Renamed Catalog")
        with self.assertRaises(ValueError):
            self.registry.delete_category(builtin.id)
        with self.assertRaises(ValueError):
            self.registry.update_category(999999, display_name="Missing")

        manual_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Manual Batch",
                subject_kind="generic",
                generation_strategy="manual",
                prefix=None,
                active_flag=True,
            )
        )
        self.assertIn(
            "does not support automatic generation",
            self.registry.generation_unavailable_reason(category_id=manual_id),
        )
        with self.assertRaisesRegex(ValueError, "does not use sequential generation"):
            self.registry.generate_next_code(category_id=manual_id)
        with self.assertRaisesRegex(ValueError, "does not generate SHA-256"):
            self.registry.generate_sha256_key(system_key=BUILTIN_CATEGORY_CATALOG_NUMBER)
        self.assertIsNone(self.registry.fetch_entry_by_value("   "))
        self.assertEqual(self.registry.list_entries(include_unused=False), [])

    def test_external_identifier_resolution_assignment_and_suggestions_cover_contract_paths(self):
        contract_id = self._create_contract(title="External Contract Number")
        with self.conn:
            self.conn.execute(
                """
                UPDATE Contracts
                SET contract_number=?,
                    contract_registry_entry_id=NULL,
                    contract_external_code_identifier_id=NULL
                WHERE id=?
                """,
                ("RAW-CTR-77", contract_id),
            )

        self.assertIn(
            "RAW-CTR-77",
            self.registry.external_identifier_suggestions(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER
            ),
        )
        self.assertEqual(
            self.registry.external_identifier_suggestions(system_key="unsupported"), []
        )

        resolution = self.registry.resolve_identifier_input(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            mode=CATALOG_MODE_EXTERNAL,
            value="EXT-CTR-88",
            created_via="test.external",
        )
        internal_id, external_id, value = self.registry.assign_identifier_to_owner(
            owner_kind="contract",
            owner_id=contract_id,
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            resolution=resolution,
            provenance_kind="manual",
            source_label="test.external",
        )
        self.assertIsNone(internal_id)
        self.assertIsNotNone(external_id)
        self.assertEqual(value, "EXT-CTR-88")
        external_record = self.registry.fetch_external_code_identifier(external_id)
        self.assertIsNotNone(external_record)
        assert external_record is not None
        self.assertTrue(external_record.linked_flag)

        stored = self.registry.list_external_code_identifiers(
            search_text="EXT-CTR",
            category_system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
        )
        self.assertEqual([record.id for record in stored], [external_id])

        with self.assertRaises(ValueError):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                mode=CATALOG_MODE_INTERNAL,
                value="bad",
                external_identifier_id=external_id,
            )
        with self.assertRaises(ValueError):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                mode=CATALOG_MODE_EXTERNAL,
                value="bad",
                registry_entry_id=999999,
            )

    def test_schema_filters_transactions_and_listing_edges(self):
        self.assertEqual(self.registry._table_columns("bad table name"), set())
        self.assertIsNone(self.registry._catalog_external_column_name("MissingOwners"))
        self.assertIsNone(
            self.registry._owner_identifier_columns(
                owner_kind="contract",
                system_key="unsupported",
            )
        )
        self.assertIsNone(
            self.registry._owner_identifier_columns(
                owner_kind="album",
                system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            )
        )
        self.assertEqual(
            self.registry._persisted_external_status("migration_conflict"),
            "migration_conflict",
        )
        self.assertEqual(
            self.registry._persisted_external_status("shadowed_by_internal"),
            "shadowed_by_internal",
        )
        reason = self.registry._classification_reason_for_external_storage(
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            classification=CodeIdentifierClassification(
                input_value="a" * 64,
                normalized_value="a" * 64,
                classification=CLASSIFICATION_INTERNAL,
            ),
        )
        self.assertIn("Valid-looking external key", reason)

        with self.assertRaisesRegex(RuntimeError, "rollback category"):
            with self.registry._immediate_transaction() as cursor:
                self.registry.create_category(
                    CodeRegistryCategoryPayload(
                        display_name="Rollback Category",
                        subject_kind="generic",
                        generation_strategy="manual",
                    ),
                    cursor=cursor,
                )
                raise RuntimeError("rollback category")
        self.assertFalse(
            any(
                category.display_name == "Rollback Category"
                for category in self.registry.list_categories()
            )
        )

        active_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Active Generic",
                subject_kind="generic",
                generation_strategy="manual",
                active_flag=True,
                sort_order=51,
            )
        )
        inactive_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Inactive Sequential",
                subject_kind="generic",
                generation_strategy="sequential",
                prefix="INA",
                active_flag=False,
                sort_order=52,
            )
        )
        active_generics = self.registry.list_categories(
            subject_kind="generic",
            active_only=True,
        )
        self.assertIn(active_id, {category.id for category in active_generics})
        self.assertNotIn(inactive_id, {category.id for category in active_generics})
        self.assertEqual(
            self.registry.generation_unavailable_reason(category_id=999999),
            "Code registry category was not found.",
        )
        with self.assertRaisesRegex(ValueError, "inactive"):
            self.registry.generate_next_code(category_id=inactive_id)

        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        catalog_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.listing",
        ).entry
        contract_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.listing",
        ).entry
        contract_entries = self.registry.list_entries(
            subject_kind="contract",
            search_text="CTR",
        )
        self.assertEqual([entry.id for entry in contract_entries], [contract_entry.id])
        contract_choices = self.registry.list_choices_for_subject(subject_kind="contract")
        catalog_choices = self.registry.list_choices_for_subject(
            subject_kind="catalog",
            category_id=catalog_entry.category_id,
        )
        self.assertEqual(contract_choices[0].label, contract_entry.value)
        self.assertIn("Catalog Number:", catalog_choices[0].label)

        with self.assertRaisesRegex(ValueError, "was not found"):
            self.registry.delete_entry(999999)

        blocked_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.delete.blocked",
        ).entry
        self.conn.execute("""
            CREATE TRIGGER block_registry_entry_delete
            BEFORE DELETE ON CodeRegistryEntries
            BEGIN
                SELECT RAISE(ABORT, 'blocked registry delete');
            END
            """)
        try:
            with self.assertRaisesRegex(ValueError, "could not be deleted"):
                self.registry.delete_entry(blocked_entry.id)
        finally:
            self.conn.execute("DROP TRIGGER block_registry_entry_delete")

    def test_identifier_resolution_assignment_and_minimal_schema_edges(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        catalog_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            created_via="test.resolve",
        ).entry
        contract_entry = self.registry.generate_next_code(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            created_via="test.resolve",
        ).entry
        contract_external = self.registry.store_external_code_identifier(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            value="EXT-CTR-200",
            provenance_kind="manual",
            source_label="test.resolve",
            owner_kind="contract",
            owner_id=0,
        )

        inferred_internal = self.registry.resolve_identifier_input(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            mode="",
            value=None,
            registry_entry_id=catalog_entry.id,
        )
        inferred_external = self.registry.resolve_identifier_input(
            system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
            mode="",
            value=None,
            external_identifier_id=contract_external.id,
        )
        self.assertEqual(inferred_internal.mode, CATALOG_MODE_INTERNAL)
        self.assertEqual(inferred_external.mode, CATALOG_MODE_EXTERNAL)

        with self.assertRaisesRegex(ValueError, "not found"):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                mode=CATALOG_MODE_INTERNAL,
                value=None,
                registry_entry_id=999999,
            )
        with self.assertRaisesRegex(ValueError, "different category"):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                mode=CATALOG_MODE_INTERNAL,
                value=None,
                registry_entry_id=catalog_entry.id,
            )
        with self.assertRaisesRegex(ValueError, "external identifier was not found"):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                mode=CATALOG_MODE_EXTERNAL,
                value=None,
                external_identifier_id=999999,
            )
        with self.assertRaisesRegex(ValueError, "different category"):
            self.registry.resolve_identifier_input(
                system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
                mode=CATALOG_MODE_EXTERNAL,
                value=None,
                external_identifier_id=contract_external.id,
            )
        with self.assertRaisesRegex(ValueError, "Unsupported identifier owner"):
            self.registry.assign_identifier_to_owner(
                owner_kind="contract",
                owner_id=1,
                system_key="unsupported",
                resolution=CodeIdentifierResolution(
                    mode=CATALOG_MODE_EMPTY,
                    category_system_key="unsupported",
                ),
            )
        with self.assertRaisesRegex(ValueError, "both internal and external"):
            self.registry.assign_identifier_to_owner(
                owner_kind="contract",
                owner_id=1,
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                resolution=CodeIdentifierResolution(
                    mode=CATALOG_MODE_INTERNAL,
                    category_system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                    value=contract_entry.value,
                    registry_entry_id=contract_entry.id,
                    external_identifier_id=contract_external.id,
                ),
            )
        with self.assertRaisesRegex(ValueError, "both internal and external"):
            self.registry.assign_identifier_to_owner(
                owner_kind="contract",
                owner_id=1,
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                resolution=CodeIdentifierResolution(
                    mode=CATALOG_MODE_EXTERNAL,
                    category_system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                    value="EXT-CTR-201",
                    registry_entry_id=contract_entry.id,
                ),
            )

        minimal_conn = sqlite3.connect(":memory:")
        try:
            minimal_conn.execute("""
                CREATE TABLE Contracts (
                    id INTEGER PRIMARY KEY,
                    contract_number TEXT,
                    contract_registry_entry_id INTEGER
                )
                """)
            minimal_conn.execute(
                "INSERT INTO Contracts(id, contract_number, contract_registry_entry_id) VALUES(1, 'OLD', 7)"
            )
            minimal_registry = object.__new__(CodeRegistryService)
            minimal_registry.conn = minimal_conn
            external_resolution = CodeIdentifierResolution(
                mode=CATALOG_MODE_EXTERNAL,
                category_system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                value="EXT",
            )
            with self.assertRaisesRegex(ValueError, "does not support external"):
                minimal_registry.assign_identifier_to_owner(
                    owner_kind="contract",
                    owner_id=1,
                    system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                    resolution=external_resolution,
                )
            cleared = minimal_registry.assign_identifier_to_owner(
                owner_kind="contract",
                owner_id=1,
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                resolution=CodeIdentifierResolution(
                    mode=CATALOG_MODE_EMPTY,
                    category_system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                ),
            )
            self.assertEqual(cleared, (None, None, None))
            self.assertEqual(
                minimal_conn.execute(
                    "SELECT contract_number, contract_registry_entry_id FROM Contracts WHERE id=1"
                ).fetchone(),
                (None, None),
            )
            self.assertIsNone(minimal_registry.fetch_external_code_identifier(1))
            self.assertEqual(minimal_registry.usage_for_external_identifier(1), [])

            minimal_conn.execute("""
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    catalog_number TEXT,
                    catalog_registry_entry_id INTEGER
                )
                """)
            minimal_conn.execute(
                "INSERT INTO Tracks(id, catalog_number, catalog_registry_entry_id) VALUES(1, NULL, NULL)"
            )
            with self.assertRaisesRegex(ValueError, "External catalog identifier storage"):
                minimal_registry.ensure_catalog_value_for_owner(owner_kind="track", owner_id=1)
        finally:
            minimal_conn.close()

    def test_capture_generation_and_sequence_failure_edges(self):
        with self.assertRaisesRegex(ValueError, "value is required"):
            self.registry.capture_value_for_category(
                system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                value="",
            )
        with self.assertRaisesRegex(ValueError, "64 lowercase hexadecimal"):
            self.registry.capture_value_for_category(
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                value="not-a-sha",
            )

        sha_value = "a" * 64
        with self.conn:
            cursor = self.conn.cursor()
            captured_sha = self.registry.capture_value_for_category(
                system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                value=sha_value,
                created_via="test.capture.sha",
                cursor=cursor,
            )
        self.assertEqual(captured_sha.value, sha_value)
        original_fetch_by_value = self.registry.fetch_entry_by_value
        self.registry.fetch_entry_by_value = lambda _value: captured_sha
        try:
            self.assertEqual(
                self.registry.capture_value_for_category(
                    system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                    value=sha_value,
                ).id,
                captured_sha.id,
            )
        finally:
            self.registry.fetch_entry_by_value = original_fetch_by_value

        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        yy = datetime.now().year % 100
        with self.assertRaisesRegex(ValueError, "known internal prefix"):
            self.registry.capture_value_for_category(
                system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
                value=f"ACR{yy:02d}ABCD",
            )

        generic_id = self.registry.create_category(
            CodeRegistryCategoryPayload(
                display_name="Generic Sequential",
                subject_kind="generic",
                generation_strategy="sequential",
                prefix=None,
                active_flag=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "Set a prefix"):
            self.registry.capture_value_for_category(category_id=generic_id, value="GEN260001")
        self.registry.update_category(generic_id, prefix="GEN")
        with self.assertRaisesRegex(ValueError, "canonical GEN"):
            self.registry.capture_value_for_category(category_id=generic_id, value="BAD260001")
        with self.assertRaisesRegex(ValueError, "outside the supported"):
            self.registry.capture_value_for_category(category_id=generic_id, value="GEN260000")

        self.registry.capture_value_for_category(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=f"ACR{yy:02d}9999",
            created_via="test.overflow",
        )
        with self.assertRaisesRegex(ValueError, "No free internal sequence"):
            self.registry.generate_next_code(system_key=BUILTIN_CATEGORY_CATALOG_NUMBER)

        collision_value = hashlib.sha256(b"collision").hexdigest()
        self.registry.capture_value_for_category(
            system_key=BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
            value=collision_value,
            created_via="test.collision",
        )
        original_fetch_by_value = self.registry.fetch_entry_by_value
        collision_checks = 0

        def fake_fetch_entry_by_value(value: str):
            nonlocal collision_checks
            collision_checks += 1
            if collision_checks == 1:
                return captured_sha
            return original_fetch_by_value(value)

        self.registry.fetch_entry_by_value = fake_fetch_entry_by_value
        try:
            with mock.patch(
                "isrc_manager.code_registry.service.secrets.token_bytes",
                side_effect=[b"collision", b"fresh"],
            ):
                generated = self.registry.generate_sha256_key(created_via="test.collision").entry
        finally:
            self.registry.fetch_entry_by_value = original_fetch_by_value
        self.assertEqual(generated.value, hashlib.sha256(b"fresh").hexdigest())

        original_fetch_entry = self.registry.fetch_entry
        self.registry.fetch_entry = lambda _entry_id: None
        try:
            with self.assertRaisesRegex(RuntimeError, "Generated Registry SHA-256"):
                self.registry.generate_sha256_key(created_via="test.reload")
        finally:
            self.registry.fetch_entry = original_fetch_entry

    def test_external_identifier_reclassification_and_legacy_update_edges(self):
        self._set_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        yy = datetime.now().year % 100
        mismatch = self.registry.store_external_code_identifier(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value=f"ACR{yy:02d}ABCD",
            provenance_kind="import",
            source_label="test.reclassify",
        )
        retained = self.registry.store_external_code_identifier(
            system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            value="IMPORT VALUE",
            provenance_kind="import",
            source_label="test.reclassify",
        )

        result = self.registry.reclassify_external_code_identifiers(
            category_system_key=BUILTIN_CATEGORY_CATALOG_NUMBER
        )
        self.assertGreaterEqual(result["mismatched"], 1)
        self.assertGreaterEqual(result["retained_external"], 1)
        self.assertEqual(
            self.registry.fetch_external_code_identifier(mismatch.id).classification_status,
            "mismatch",
        )
        self.assertEqual(
            self.registry.fetch_external_code_identifier(retained.id).classification_status,
            "external",
        )
        with self.assertRaisesRegex(ValueError, "was not found"):
            self.registry.promote_external_code_identifier(999999)

        legacy_conn = sqlite3.connect(":memory:")
        try:
            legacy_conn.executescript("""
                CREATE TABLE CodeRegistryCategories (
                    id INTEGER PRIMARY KEY,
                    system_key TEXT UNIQUE,
                    display_name TEXT,
                    subject_kind TEXT,
                    generation_strategy TEXT,
                    prefix TEXT,
                    normalized_prefix TEXT,
                    active_flag INTEGER,
                    sort_order INTEGER,
                    is_system INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE CodeRegistrySequences (
                    category_id INTEGER,
                    sequence_year INTEGER,
                    last_sequence_number INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY(category_id, sequence_year)
                );
                CREATE TABLE CodeRegistryEntries (
                    id INTEGER PRIMARY KEY,
                    category_id INTEGER,
                    value TEXT,
                    normalized_value TEXT,
                    entry_kind TEXT,
                    prefix_snapshot TEXT,
                    sequence_year INTEGER,
                    sequence_number INTEGER,
                    immutable_flag INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    created_via TEXT,
                    notes TEXT
                );
                CREATE TABLE ExternalCatalogIdentifiers (
                    id INTEGER PRIMARY KEY,
                    subject_kind TEXT NOT NULL,
                    subject_id INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    provenance_kind TEXT NOT NULL DEFAULT 'manual',
                    classification_status TEXT NOT NULL DEFAULT 'external',
                    classification_reason TEXT,
                    source_label TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    track_title TEXT,
                    catalog_number TEXT,
                    catalog_registry_entry_id INTEGER,
                    external_catalog_identifier_id INTEGER
                );
                CREATE TABLE Releases (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    primary_artist TEXT,
                    catalog_number TEXT,
                    catalog_registry_entry_id INTEGER,
                    external_catalog_identifier_id INTEGER
                );
                CREATE TABLE Contracts (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    contract_number TEXT,
                    contract_registry_entry_id INTEGER,
                    license_number TEXT,
                    license_registry_entry_id INTEGER,
                    registry_sha256_key TEXT,
                    registry_sha256_key_entry_id INTEGER
                );
                """)
            legacy_registry = CodeRegistryService(legacy_conn)
            legacy_registry.update_category(
                legacy_registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER).id,
                prefix="LGC",
            )
            with legacy_conn:
                cursor = legacy_conn.cursor()
                first_external_id = legacy_registry._upsert_external_code_identifier(
                    system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
                    owner_kind="track",
                    owner_id=1,
                    value="LEGACY-CAT",
                    provenance_kind="import",
                    classification_status="external",
                    classification_reason="first",
                    source_label="legacy",
                    cursor=cursor,
                )
                second_external_id = legacy_registry._upsert_external_code_identifier(
                    system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
                    owner_kind="track",
                    owner_id=1,
                    value="LEGACY-CAT",
                    provenance_kind="manual",
                    classification_status="external",
                    classification_reason="updated",
                    source_label="legacy-update",
                    cursor=cursor,
                )
                with self.assertRaisesRegex(ValueError, "only supports catalog"):
                    legacy_registry._upsert_external_code_identifier(
                        system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
                        owner_kind="contract",
                        owner_id=1,
                        value="LIC-LEGACY",
                        provenance_kind="manual",
                        classification_status="external",
                        classification_reason=None,
                        source_label=None,
                        cursor=cursor,
                    )
            self.assertEqual(first_external_id, second_external_id)
            legacy_record = legacy_registry.fetch_external_catalog_identifier(first_external_id)
            self.assertEqual(legacy_record.classification_reason, "updated")
            self.assertEqual(legacy_record.source_label, "legacy-update")

            canonical_value = f"LGC{yy:02d}0001"
            with legacy_conn:
                cursor = legacy_conn.cursor()
                promotable_external_id = legacy_registry._upsert_external_code_identifier(
                    system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
                    owner_kind="track",
                    owner_id=7,
                    value=canonical_value,
                    provenance_kind="import",
                    classification_status="external",
                    classification_reason="promotable",
                    source_label="legacy-promote",
                    cursor=cursor,
                )
                legacy_conn.execute(
                    """
                    INSERT INTO Tracks(
                        id,
                        track_title,
                        catalog_number,
                        catalog_registry_entry_id,
                        external_catalog_identifier_id
                    )
                    VALUES(7, 'Legacy Promote', ?, NULL, ?)
                    """,
                    (canonical_value, promotable_external_id),
                )
            promoted = legacy_registry.promote_external_catalog_identifier(
                promotable_external_id,
                created_via="test.legacy.promote",
            )
            promoted_row = legacy_conn.execute("""
                SELECT catalog_number, catalog_registry_entry_id, external_catalog_identifier_id
                FROM Tracks
                WHERE id=7
                """).fetchone()
            shadowed = legacy_registry.fetch_external_catalog_identifier(promotable_external_id)

            self.assertEqual(promoted.value, canonical_value)
            self.assertEqual(promoted_row, (canonical_value, promoted.id, None))
            self.assertEqual(shadowed.classification_status, "shadowed_by_internal")
        finally:
            legacy_conn.close()

    def test_legacy_external_catalog_identifier_schema_remains_readable(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript("""
                CREATE TABLE CodeRegistryCategories (
                    id INTEGER PRIMARY KEY,
                    system_key TEXT UNIQUE,
                    display_name TEXT,
                    subject_kind TEXT,
                    generation_strategy TEXT,
                    prefix TEXT,
                    normalized_prefix TEXT,
                    active_flag INTEGER,
                    sort_order INTEGER,
                    is_system INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE CodeRegistrySequences (
                    category_id INTEGER,
                    sequence_year INTEGER,
                    next_sequence_number INTEGER,
                    PRIMARY KEY(category_id, sequence_year)
                );
                CREATE TABLE CodeRegistryEntries (
                    id INTEGER PRIMARY KEY,
                    category_id INTEGER,
                    value TEXT,
                    normalized_value TEXT,
                    entry_kind TEXT,
                    prefix_snapshot TEXT,
                    sequence_year INTEGER,
                    sequence_number INTEGER,
                    immutable_flag INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    created_via TEXT,
                    notes TEXT
                );
                CREATE TABLE ExternalCatalogIdentifiers (
                    id INTEGER PRIMARY KEY,
                    subject_kind TEXT NOT NULL,
                    subject_id INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    provenance_kind TEXT NOT NULL DEFAULT 'manual',
                    classification_status TEXT NOT NULL DEFAULT 'external',
                    classification_reason TEXT,
                    source_label TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    track_title TEXT,
                    catalog_number TEXT,
                    catalog_registry_entry_id INTEGER,
                    external_catalog_identifier_id INTEGER
                );
                CREATE TABLE Releases (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    primary_artist TEXT,
                    catalog_number TEXT,
                    catalog_registry_entry_id INTEGER,
                    external_catalog_identifier_id INTEGER
                );
                CREATE TABLE Contracts (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    contract_number TEXT,
                    contract_registry_entry_id INTEGER,
                    license_number TEXT,
                    license_registry_entry_id INTEGER,
                    registry_sha256_key TEXT,
                    registry_sha256_key_entry_id INTEGER
                );
                """)
            conn.execute("""
                INSERT INTO ExternalCatalogIdentifiers(
                    id,
                    subject_kind,
                    subject_id,
                    value,
                    normalized_value,
                    provenance_kind,
                    classification_status,
                    source_label
                )
                VALUES(1, 'track', 10, 'LEGACY-CAT-1', 'legacy-cat-1', 'imported', 'external', 'legacy import')
                """)
            conn.execute("""
                INSERT INTO Tracks(
                    id,
                    track_title,
                    catalog_number,
                    catalog_registry_entry_id,
                    external_catalog_identifier_id
                )
                VALUES(10, 'Legacy Track', 'LEGACY-CAT-1', NULL, 1)
                """)
            registry = CodeRegistryService(conn)

            self.assertEqual(
                registry._external_identifier_table_name(), "ExternalCatalogIdentifiers"
            )
            self.assertTrue(registry._using_legacy_external_catalog_schema())
            self.assertEqual(
                registry.list_external_code_identifiers(
                    category_system_key=BUILTIN_CATEGORY_LICENSE_NUMBER,
                ),
                [],
            )
            records = registry.list_external_code_identifiers(
                search_text="LEGACY",
                category_system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            )
            suggestions = registry.external_identifier_suggestions(
                system_key=BUILTIN_CATEGORY_CATALOG_NUMBER,
            )

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].category_system_key, BUILTIN_CATEGORY_CATALOG_NUMBER)
            self.assertEqual(records[0].value, "LEGACY-CAT-1")
            self.assertEqual(records[0].origin_record_kind, "track")
            self.assertEqual(records[0].origin_record_id, 10)
            self.assertEqual(records[0].usage_count, 1)
            self.assertTrue(records[0].linked_flag)
            self.assertIn("LEGACY-CAT-1", suggestions)
        finally:
            conn.close()

    def test_registry_initialization_is_noop_until_schema_exists(self):
        conn = sqlite3.connect(":memory:")
        try:
            registry = CodeRegistryService(conn)

            self.assertFalse(registry._registry_schema_ready())
            self.assertEqual(registry._external_identifier_table_name(), None)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

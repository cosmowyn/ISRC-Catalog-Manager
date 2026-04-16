import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
    BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
    CodeRegistryService,
)
from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.parties import PartyService
from isrc_manager.services import DatabaseSchemaService


class DatabaseSchemaMigrations3940Tests(unittest.TestCase):
    def test_migrate_39_to_40_generalizes_external_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                service = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                service.init_db()

                registry = CodeRegistryService(conn)
                for system_key, prefix in (
                    (BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR"),
                    (BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR"),
                    (BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC"),
                ):
                    category = registry.fetch_category_by_system_key(system_key)
                    self.assertIsNotNone(category)
                    assert category is not None
                    registry.update_category(category.id, prefix=prefix)

                artist_id = int(PartyService(conn).ensure_artist_party_by_name("Migration Artist"))

                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("DROP TABLE IF EXISTS ReleaseTracks")
                conn.execute("DROP TABLE IF EXISTS TrackArtists")
                conn.execute("DROP TABLE IF EXISTS ContractParties")
                conn.execute("DROP TABLE IF EXISTS ContractObligations")
                conn.execute("DROP TABLE IF EXISTS ContractDocuments")
                conn.execute("DROP TABLE IF EXISTS ContractWorkLinks")
                conn.execute("DROP TABLE IF EXISTS ContractTrackLinks")
                conn.execute("DROP TABLE IF EXISTS ContractReleaseLinks")
                conn.execute("DROP TABLE IF EXISTS Tracks")
                conn.execute("DROP TABLE IF EXISTS Releases")
                conn.execute("DROP TABLE IF EXISTS Contracts")
                conn.execute("DROP TABLE IF EXISTS ExternalCodeIdentifiers")
                conn.execute(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        db_entry_date DATE,
                        track_title TEXT NOT NULL,
                        catalog_number TEXT,
                        catalog_registry_entry_id INTEGER,
                        external_catalog_identifier_id INTEGER,
                        main_artist_party_id INTEGER NOT NULL,
                        track_length_sec INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE Releases (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        primary_artist TEXT,
                        release_type TEXT NOT NULL DEFAULT 'album',
                        catalog_number TEXT,
                        catalog_registry_entry_id INTEGER,
                        external_catalog_identifier_id INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE Contracts (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        contract_type TEXT,
                        contract_number TEXT,
                        license_number TEXT,
                        registry_sha256_key TEXT,
                        contract_registry_entry_id INTEGER,
                        license_registry_entry_id INTEGER,
                        registry_sha256_key_entry_id INTEGER,
                        draft_date TEXT,
                        signature_date TEXT,
                        effective_date TEXT,
                        start_date TEXT,
                        end_date TEXT,
                        renewal_date TEXT,
                        notice_deadline TEXT,
                        option_periods TEXT,
                        reversion_date TEXT,
                        termination_date TEXT,
                        status TEXT NOT NULL DEFAULT 'draft',
                        supersedes_contract_id INTEGER,
                        superseded_by_contract_id INTEGER,
                        summary TEXT,
                        notes TEXT,
                        profile_name TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                conn.execute("DELETE FROM ExternalCatalogIdentifiers")
                conn.executemany(
                    """
                    INSERT INTO ExternalCatalogIdentifiers(
                        id,
                        subject_kind,
                        subject_id,
                        value,
                        normalized_value,
                        provenance_kind,
                        classification_status,
                        classification_reason,
                        source_label
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            1,
                            "track",
                            1,
                            "EXT-TRACK-001",
                            "ext-track-001",
                            "migration",
                            "external",
                            "legacy track external",
                            "legacy_39",
                        ),
                        (
                            2,
                            "release",
                            1,
                            "EXT-REL-001",
                            "ext-rel-001",
                            "migration",
                            "external",
                            "legacy release external",
                            "legacy_39",
                        ),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(
                        id,
                        isrc,
                        isrc_compact,
                        db_entry_date,
                        track_title,
                        catalog_number,
                        catalog_registry_entry_id,
                        external_catalog_identifier_id,
                        main_artist_party_id,
                        track_length_sec
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "NL-TST-26-90001",
                        "NLTST2690001",
                        "2026-04-16",
                        "Legacy External Track",
                        "EXT-TRACK-001",
                        None,
                        1,
                        artist_id,
                        201,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO Releases(
                        id,
                        title,
                        primary_artist,
                        release_type,
                        catalog_number,
                        catalog_registry_entry_id,
                        external_catalog_identifier_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "Legacy External Release",
                        "Migration Artist",
                        "album",
                        "EXT-REL-001",
                        None,
                        2,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO Contracts(
                        id,
                        title,
                        contract_type,
                        contract_number,
                        license_number,
                        registry_sha256_key,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "Legacy Classified Contract",
                        "license",
                        "CTR260001",
                        "LIC260001",
                        "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
                        "draft",
                    ),
                )
                conn.execute("PRAGMA user_version = 39")
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()

                service.migrate_schema()

                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)

                track_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()
                }
                release_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(Releases)").fetchall()
                }
                contract_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(Contracts)").fetchall()
                }
                self.assertIn("catalog_external_code_identifier_id", track_columns)
                self.assertNotIn("external_catalog_identifier_id", track_columns)
                self.assertIn("catalog_external_code_identifier_id", release_columns)
                self.assertNotIn("external_catalog_identifier_id", release_columns)
                self.assertIn("contract_external_code_identifier_id", contract_columns)
                self.assertIn("license_external_code_identifier_id", contract_columns)
                self.assertIn("registry_sha256_key_external_code_identifier_id", contract_columns)

                track_sql = conn.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type='table' AND name='Tracks'
                    """
                ).fetchone()[0]
                contract_sql = conn.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type='table' AND name='Contracts'
                    """
                ).fetchone()[0]
                self.assertIn("catalog_registry_entry_id IS NULL", track_sql)
                self.assertIn("contract_registry_entry_id IS NULL", contract_sql)
                self.assertIn("license_registry_entry_id IS NULL", contract_sql)
                self.assertIn("registry_sha256_key_entry_id IS NULL", contract_sql)

                track_row = conn.execute(
                    """
                    SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
                    FROM Tracks
                    WHERE id=1
                    """
                ).fetchone()
                release_row = conn.execute(
                    """
                    SELECT catalog_number, catalog_registry_entry_id, catalog_external_code_identifier_id
                    FROM Releases
                    WHERE id=1
                    """
                ).fetchone()
                contract_row = conn.execute(
                    """
                    SELECT
                        contract_number,
                        contract_registry_entry_id,
                        contract_external_code_identifier_id,
                        license_number,
                        license_registry_entry_id,
                        license_external_code_identifier_id,
                        registry_sha256_key,
                        registry_sha256_key_entry_id,
                        registry_sha256_key_external_code_identifier_id
                    FROM Contracts
                    WHERE id=1
                    """
                ).fetchone()

                self.assertEqual(track_row, ("EXT-TRACK-001", None, 1))
                self.assertEqual(release_row, ("EXT-REL-001", None, 2))
                self.assertEqual(contract_row[0], "CTR260001")
                self.assertIsNotNone(contract_row[1])
                self.assertIsNone(contract_row[2])
                self.assertEqual(contract_row[3], "LIC260001")
                self.assertIsNotNone(contract_row[4])
                self.assertIsNone(contract_row[5])
                self.assertEqual(
                    contract_row[6],
                    "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
                )
                self.assertIsNone(contract_row[7])
                self.assertIsNotNone(contract_row[8])

                external_rows = conn.execute(
                    """
                    SELECT category_system_key, value
                    FROM ExternalCodeIdentifiers
                    ORDER BY id
                    """
                ).fetchall()
                self.assertEqual(
                    external_rows[:2],
                    [
                        (BUILTIN_CATEGORY_CATALOG_NUMBER, "EXT-TRACK-001"),
                        (BUILTIN_CATEGORY_CATALOG_NUMBER, "EXT-REL-001"),
                    ],
                )
                self.assertIn(
                    (
                        BUILTIN_CATEGORY_REGISTRY_SHA256_KEY,
                        "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
                    ),
                    external_rows,
                )

                diagnostics = {
                    (row[0], row[1]): int(row[2] or 0)
                    for row in conn.execute(
                        """
                        SELECT category_system_key, diagnostic_key, diagnostic_count
                        FROM _MigrationDiagnostics
                        WHERE migration_version=40
                        """
                    ).fetchall()
                }
                self.assertEqual(
                    diagnostics[(BUILTIN_CATEGORY_CATALOG_NUMBER, "legacy_external_rows")], 2
                )
                self.assertEqual(
                    diagnostics[(BUILTIN_CATEGORY_CONTRACT_NUMBER, "internal_authority")], 1
                )
                self.assertEqual(
                    diagnostics[(BUILTIN_CATEGORY_LICENSE_NUMBER, "internal_authority")], 1
                )
                self.assertEqual(
                    diagnostics[(BUILTIN_CATEGORY_REGISTRY_SHA256_KEY, "external_authority")], 1
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

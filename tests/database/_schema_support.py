import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService


class DatabaseSchemaServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.service = DatabaseSchemaService(self.conn)

    def tearDown(self):
        self.conn.close()

    def case_init_db_and_migrate_schema_reach_current_target(self):
        self.service.init_db()
        self.service.migrate_schema()

        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        value_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
        }
        custom_field_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(CustomFieldDefs)").fetchall()
        }
        album_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(Albums)").fetchall()
        }
        track_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(Tracks)").fetchall()
        }
        gs1_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(GS1Metadata)").fetchall()
        }
        history_entry_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(HistoryEntries)").fetchall()
        }
        authenticity_key_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(AuthenticityKeys)").fetchall()
        }
        authenticity_manifest_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(AuthenticityManifests)").fetchall()
        }
        derivative_batch_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(DerivativeExportBatches)").fetchall()
        }
        track_audio_derivative_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(TrackAudioDerivatives)").fetchall()
        }
        track_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(Tracks)").fetchall()
        }
        gs1_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(GS1Metadata)").fetchall()
        }
        authenticity_manifest_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(AuthenticityManifests)").fetchall()
        }
        derivative_batch_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(DerivativeExportBatches)").fetchall()
        }
        track_audio_derivative_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(TrackAudioDerivatives)").fetchall()
        }
        triggers = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }

        self.assertEqual(self.service.get_db_version(), SCHEMA_TARGET)
        self.assertIn("HistoryEntries", tables)
        self.assertIn("HistoryBackups", tables)
        self.assertIn("HistorySnapshots", tables)
        self.assertIn("HistoryHead", tables)
        self.assertIn("Licensees", tables)
        self.assertIn("GS1Metadata", tables)
        self.assertIn("GS1TemplateStorage", tables)
        self.assertIn("Releases", tables)
        self.assertIn("ReleaseTracks", tables)
        self.assertIn("Parties", tables)
        self.assertIn("Works", tables)
        self.assertIn("WorkContributors", tables)
        self.assertIn("WorkTrackLinks", tables)
        self.assertIn("Contracts", tables)
        self.assertIn("ContractParties", tables)
        self.assertIn("ContractObligations", tables)
        self.assertIn("ContractDocuments", tables)
        self.assertIn("RightsRecords", tables)
        self.assertIn("AssetVersions", tables)
        self.assertIn("SavedSearches", tables)
        self.assertIn("AuthenticityKeys", tables)
        self.assertIn("AuthenticityManifests", tables)
        self.assertIn("DerivativeExportBatches", tables)
        self.assertIn("TrackAudioDerivatives", tables)
        self.assertIn("vw_Licenses", tables)
        self.assertIn("contract_number", gs1_columns)
        self.assertIn("visible_in_history", history_entry_columns)
        self.assertIn("blob_icon_payload", custom_field_columns)
        self.assertTrue(
            {"key_id", "algorithm", "signer_label", "public_key_b64", "created_at"}
            <= authenticity_key_columns
        )
        self.assertTrue(
            {
                "track_id",
                "reference_asset_id",
                "key_id",
                "manifest_id",
                "watermark_id",
                "watermark_nonce",
                "manifest_digest_prefix",
                "payload_canonical",
                "payload_sha256",
                "signature_b64",
                "reference_audio_sha256",
                "reference_fingerprint_b64",
                "reference_source_kind",
                "embed_settings_json",
            }
            <= authenticity_manifest_columns
        )
        self.assertTrue(
            {
                "batch_id",
                "schema_version",
                "workflow_kind",
                "derivative_kind",
                "authenticity_basis",
                "package_mode",
                "recipe_canonical",
                "recipe_sha256",
                "requested_count",
                "exported_count",
                "skipped_count",
                "created_at",
                "status",
            }
            <= derivative_batch_columns
        )
        self.assertTrue(
            {
                "export_id",
                "batch_id",
                "track_id",
                "sequence_no",
                "target_key",
                "workflow_kind",
                "derivative_kind",
                "authenticity_basis",
                "source_kind",
                "source_asset_id",
                "source_audio_sha256",
                "derivative_asset_id",
                "parent_manifest_id",
                "derivative_manifest_id",
                "output_format",
                "output_suffix",
                "output_filename",
                "filename_hash_suffix",
                "output_sha256",
                "managed_file_path",
                "sidecar_path",
                "package_member_path",
                "status",
            }
            <= track_audio_derivative_columns
        )
        self.assertTrue({"blob_value", "mime_type", "size_bytes"} <= value_columns)
        self.assertTrue(
            {
                "album_art_path",
                "album_art_mime_type",
                "album_art_size_bytes",
            }
            <= album_columns
        )
        self.assertTrue(
            {
                "audio_file_path",
                "audio_file_mime_type",
                "audio_file_size_bytes",
                "catalog_number",
                "album_art_path",
                "album_art_mime_type",
                "album_art_size_bytes",
                "buma_work_number",
                "composer",
                "publisher",
                "comments",
                "lyrics",
                "repertoire_status",
                "metadata_complete",
                "contract_signed",
                "rights_verified",
            }
            <= track_columns
        )
        self.assertIn("idx_tracks_isrc_compact_unique", track_indexes)
        self.assertIn("idx_tracks_catalog_number", track_indexes)
        self.assertIn("idx_tracks_buma_work_number", track_indexes)
        self.assertIn("idx_gs1_metadata_export_enabled", gs1_indexes)
        self.assertIn("idx_gs1_metadata_contract_number", gs1_indexes)
        self.assertIn("idx_authenticity_manifests_manifest_id", authenticity_manifest_indexes)
        self.assertIn("idx_authenticity_manifests_track_id", authenticity_manifest_indexes)
        self.assertIn("idx_authenticity_manifests_watermark_id", authenticity_manifest_indexes)
        self.assertIn("idx_authenticity_manifests_key_id", authenticity_manifest_indexes)
        self.assertIn("idx_authenticity_manifests_payload_sha256", authenticity_manifest_indexes)
        self.assertIn("idx_derivative_export_batches_batch_id", derivative_batch_indexes)
        self.assertIn("idx_derivative_export_batches_created_at", derivative_batch_indexes)
        self.assertIn("idx_derivative_export_batches_status", derivative_batch_indexes)
        self.assertIn("idx_derivative_export_batches_workflow_kind", derivative_batch_indexes)
        self.assertIn("idx_derivative_export_batches_derivative_kind", derivative_batch_indexes)
        self.assertIn(
            "idx_derivative_export_batches_authenticity_basis",
            derivative_batch_indexes,
        )
        self.assertIn("idx_track_audio_derivatives_export_id", track_audio_derivative_indexes)
        self.assertIn("idx_track_audio_derivatives_batch_id", track_audio_derivative_indexes)
        self.assertIn("idx_track_audio_derivatives_track_id", track_audio_derivative_indexes)
        self.assertIn(
            "idx_track_audio_derivatives_workflow_kind",
            track_audio_derivative_indexes,
        )
        self.assertIn(
            "idx_track_audio_derivatives_derivative_kind",
            track_audio_derivative_indexes,
        )
        self.assertIn(
            "idx_track_audio_derivatives_authenticity_basis",
            track_audio_derivative_indexes,
        )
        self.assertIn(
            "idx_track_audio_derivatives_derivative_manifest_id",
            track_audio_derivative_indexes,
        )
        self.assertIn("trg_auditlog_no_update", triggers)

    def case_migrate_20_to_21_adds_repertoire_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 20")
            conn.execute("DROP TABLE IF EXISTS Parties")
            conn.execute("DROP TABLE IF EXISTS Works")
            conn.execute("DROP TABLE IF EXISTS Contracts")
            conn.execute("DROP TABLE IF EXISTS RightsRecords")
            conn.execute("DROP TABLE IF EXISTS AssetVersions")
            conn.execute("DROP TABLE IF EXISTS SavedSearches")
            conn.commit()

            service.migrate_schema()

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "Parties",
                    "Works",
                    "Contracts",
                    "RightsRecords",
                    "AssetVersions",
                    "SavedSearches",
                }
                <= tables
            )
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_21_to_22_adds_blob_icon_payload_column(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 21")
            conn.execute("DROP TABLE IF EXISTS CustomFieldDefs")
            conn.execute(
                """
                CREATE TABLE CustomFieldDefs (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER,
                    field_type TEXT NOT NULL DEFAULT 'text',
                    options TEXT
                )
                """
            )
            conn.commit()

            service.migrate_schema()

            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(CustomFieldDefs)").fetchall()
            }
            self.assertIn("blob_icon_payload", columns)
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_23_to_24_adds_history_visibility_column(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 23")
            conn.execute("DROP TABLE IF EXISTS HistoryEntries")
            conn.execute(
                """
                CREATE TABLE HistoryEntries (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    label TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    reversible INTEGER NOT NULL DEFAULT 1,
                    strategy TEXT NOT NULL,
                    payload_json TEXT,
                    inverse_json TEXT,
                    redo_json TEXT,
                    snapshot_before_id INTEGER,
                    snapshot_after_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'applied'
                )
                """
            )
            conn.commit()

            service.migrate_schema()

            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(HistoryEntries)").fetchall()
            }
            self.assertIn("visible_in_history", columns)
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_25_to_26_adds_authenticity_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 25")
            conn.execute("DROP TABLE IF EXISTS AuthenticityManifests")
            conn.execute("DROP TABLE IF EXISTS AuthenticityKeys")
            conn.execute("DROP TABLE IF EXISTS TrackAudioDerivatives")
            conn.execute("DROP TABLE IF EXISTS DerivativeExportBatches")
            conn.commit()

            service.migrate_schema()

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            manifest_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(AuthenticityManifests)").fetchall()
            }
            derivative_batch_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(DerivativeExportBatches)").fetchall()
            }
            track_audio_derivative_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(TrackAudioDerivatives)").fetchall()
            }

            self.assertTrue(
                {
                    "AuthenticityKeys",
                    "AuthenticityManifests",
                    "DerivativeExportBatches",
                    "TrackAudioDerivatives",
                }
                <= tables
            )
            self.assertIn("idx_authenticity_manifests_manifest_id", manifest_indexes)
            self.assertIn("idx_derivative_export_batches_batch_id", derivative_batch_indexes)
            self.assertIn(
                "idx_track_audio_derivatives_export_id",
                track_audio_derivative_indexes,
            )
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_26_to_27_adds_derivative_export_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 26")
            conn.execute("DROP TABLE IF EXISTS TrackAudioDerivatives")
            conn.execute("DROP TABLE IF EXISTS DerivativeExportBatches")
            conn.commit()

            service.migrate_schema()

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            derivative_batch_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(DerivativeExportBatches)").fetchall()
            }
            track_audio_derivative_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(TrackAudioDerivatives)").fetchall()
            }

            self.assertTrue({"DerivativeExportBatches", "TrackAudioDerivatives"} <= tables)
            self.assertIn("idx_derivative_export_batches_batch_id", derivative_batch_indexes)
            self.assertIn(
                "idx_track_audio_derivatives_export_id",
                track_audio_derivative_indexes,
            )
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_27_to_28_adds_derivative_ledger_semantics(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 27")
            conn.execute("DROP TABLE IF EXISTS TrackAudioDerivatives")
            conn.execute("DROP TABLE IF EXISTS DerivativeExportBatches")
            conn.commit()

            service.migrate_schema()

            derivative_batch_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(DerivativeExportBatches)").fetchall()
            }
            track_audio_derivative_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(TrackAudioDerivatives)").fetchall()
            }

            self.assertTrue(
                {"workflow_kind", "derivative_kind", "authenticity_basis"}
                <= derivative_batch_columns
            )
            self.assertTrue(
                {"workflow_kind", "derivative_kind", "authenticity_basis"}
                <= track_audio_derivative_columns
            )
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_12_to_13_promotes_default_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        track_title TEXT NOT NULL,
                        main_artist_id INTEGER NOT NULL,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0,
                        iswc TEXT,
                        upc TEXT,
                        genre TEXT
                    );
                    CREATE TABLE CustomFieldDefs (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        active INTEGER NOT NULL DEFAULT 1,
                        sort_order INTEGER,
                        field_type TEXT NOT NULL DEFAULT 'text',
                        options TEXT
                    );
                    CREATE TABLE CustomFieldValues (
                        track_id INTEGER NOT NULL,
                        field_def_id INTEGER NOT NULL,
                        value TEXT,
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                    VALUES (1, 'NL-ABC-26-00001', 'NLABC2600001', 'Migrated Song', 1, NULL, '2026-03-13', 180, NULL, NULL, NULL)
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Catalog#", 1, "text"),
                        (2, "BUMA Wnr.", 2, "text"),
                        (3, "Audio File", 3, "blob_audio"),
                        (4, "Album Art", 4, "blob_image"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "CAT-LEGACY-01", None, None, 0),
                        (1, 2, "BUMA-LEGACY-99", None, None, 0),
                        (1, 3, None, sqlite3.Binary(b"WAVE"), "audio/wav", 4),
                        (1, 4, None, sqlite3.Binary(b"PNG!"), "image/png", 4),
                    ],
                )
                conn.execute("PRAGMA user_version = 12")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        catalog_number,
                        buma_work_number,
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        album_art_path,
                        album_art_mime_type,
                        album_art_size_bytes
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "CAT-LEGACY-01")
                self.assertEqual(row[1], "BUMA-LEGACY-99")
                self.assertTrue(str(row[2]).startswith("track_media/audio/"))
                self.assertEqual(row[3], "audio/wav")
                self.assertEqual(row[4], 4)
                self.assertTrue(str(row[5]).startswith("track_media/images/"))
                self.assertEqual(row[6], "image/png")
                self.assertEqual(row[7], 4)

                audio_path = Path(tmpdir) / str(row[2])
                art_path = Path(tmpdir) / str(row[5])
                self.assertEqual(audio_path.read_bytes(), b"WAVE")
                self.assertEqual(art_path.read_bytes(), b"PNG!")
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
                    0,
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def case_current_schema_allows_multiple_blank_isrc_rows(self):
        self.service.init_db()
        self.service.migrate_schema()

        self.conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Schema Artist')")
        self.conn.execute(
            """
            INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, track_length_sec)
            VALUES ('', '', 'Blank ISRC One', 1, 0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, track_length_sec)
            VALUES ('', '', 'Blank ISRC Two', 1, 0)
            """
        )

        rows = self.conn.execute("SELECT isrc, isrc_compact FROM Tracks ORDER BY id").fetchall()
        self.assertEqual(rows, [("", ""), ("", "")])

    def case_migrate_13_to_14_reconciles_leftover_promoted_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        db_entry_date DATE,
                        audio_file_path TEXT,
                        audio_file_mime_type TEXT,
                        audio_file_size_bytes INTEGER NOT NULL DEFAULT 0,
                        track_title TEXT NOT NULL,
                        catalog_number TEXT,
                        album_art_path TEXT,
                        album_art_mime_type TEXT,
                        album_art_size_bytes INTEGER NOT NULL DEFAULT 0,
                        main_artist_id INTEGER NOT NULL,
                        buma_work_number TEXT,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0,
                        iswc TEXT,
                        upc TEXT,
                        genre TEXT
                    );
                    CREATE TABLE CustomFieldDefs (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        active INTEGER NOT NULL DEFAULT 1,
                        sort_order INTEGER,
                        field_type TEXT NOT NULL DEFAULT 'text',
                        options TEXT
                    );
                    CREATE TABLE CustomFieldValues (
                        track_id INTEGER NOT NULL,
                        field_def_id INTEGER NOT NULL,
                        value TEXT,
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(
                        id, isrc, isrc_compact, db_entry_date,
                        audio_file_path, audio_file_mime_type, audio_file_size_bytes,
                        track_title, catalog_number,
                        album_art_path, album_art_mime_type, album_art_size_bytes,
                        main_artist_id, buma_work_number, album_id, release_date, track_length_sec, iswc, upc, genre
                    )
                    VALUES (
                        1, 'NL-ABC-26-00001', 'NLABC2600001', '2026-03-13',
                        NULL, NULL, 0,
                        'Migrated Again', NULL,
                        NULL, NULL, 0,
                        1, NULL, NULL, '2026-03-13', 180, NULL, NULL, NULL
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Catalog#", 1, "text"),
                        (2, "BUMA Wnr.", 2, "text"),
                        (3, "Audio File", 3, "blob_audio"),
                        (4, "Album Art", 4, "blob_image"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "CAT-V13-01", None, None, 0),
                        (1, 2, "BUMA-V13-88", None, None, 0),
                        (1, 3, None, sqlite3.Binary(b"AUDI"), "audio/wav", 4),
                        (1, 4, None, sqlite3.Binary(b"IMAG"), "image/png", 4),
                    ],
                )
                conn.execute("PRAGMA user_version = 13")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        catalog_number,
                        buma_work_number,
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        album_art_path,
                        album_art_mime_type,
                        album_art_size_bytes
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertEqual(row[0], "CAT-V13-01")
                self.assertEqual(row[1], "BUMA-V13-88")
                self.assertTrue(str(row[2]).startswith("track_media/audio/"))
                self.assertEqual(row[3], "audio/wav")
                self.assertEqual(row[4], 4)
                self.assertTrue(str(row[5]).startswith("track_media/images/"))
                self.assertEqual(row[6], "image/png")
                self.assertEqual(row[7], 4)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
                    0,
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def case_migration_skips_same_name_fields_with_different_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        track_title TEXT NOT NULL,
                        main_artist_id INTEGER NOT NULL,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0,
                        iswc TEXT,
                        upc TEXT,
                        genre TEXT
                    );
                    CREATE TABLE CustomFieldDefs (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        active INTEGER NOT NULL DEFAULT 1,
                        sort_order INTEGER,
                        field_type TEXT NOT NULL DEFAULT 'text',
                        options TEXT
                    );
                    CREATE TABLE CustomFieldValues (
                        track_id INTEGER NOT NULL,
                        field_def_id INTEGER NOT NULL,
                        value TEXT,
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                    VALUES (1, 'NL-ABC-26-00001', 'NLABC2600001', 'Keep Custom Types', 1, NULL, '2026-03-13', 180, NULL, NULL, NULL)
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Audio File", 1, "text"),
                        (2, "Catalog#", 2, "dropdown"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "not-a-blob", None, None, 0),
                        (1, 2, "CAT-OPTION", None, None, 0),
                    ],
                )
                conn.execute("PRAGMA user_version = 12")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        catalog_number
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertEqual(row, (None, None, 0, None))
                self.assertEqual(
                    conn.execute(
                        "SELECT name, field_type FROM CustomFieldDefs ORDER BY id"
                    ).fetchall(),
                    [("Audio File", "text"), ("Catalog#", "dropdown")],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT track_id, field_def_id, value FROM CustomFieldValues ORDER BY field_def_id"
                    ).fetchall(),
                    [(1, 1, "not-a-blob"), (1, 2, "CAT-OPTION")],
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def case_init_db_tolerates_older_tracks_schema_before_migration(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE Artists (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE Albums (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    isrc TEXT NOT NULL,
                    isrc_compact TEXT,
                    track_title TEXT NOT NULL,
                    main_artist_id INTEGER NOT NULL,
                    album_id INTEGER,
                    release_date DATE,
                    track_length_sec INTEGER NOT NULL DEFAULT 0,
                    iswc TEXT,
                    upc TEXT,
                    genre TEXT
                );
                """
            )
            service = DatabaseSchemaService(conn)

            service.init_db()

            track_columns = {row[1] for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()}
            track_indexes = {row[1] for row in conn.execute("PRAGMA index_list(Tracks)").fetchall()}
            self.assertTrue(
                {
                    "db_entry_date",
                    "isrc_compact",
                    "track_length_sec",
                    "audio_file_path",
                    "audio_file_mime_type",
                    "audio_file_size_bytes",
                    "catalog_number",
                    "album_art_path",
                    "album_art_mime_type",
                    "album_art_size_bytes",
                    "buma_work_number",
                }
                <= track_columns
            )
            self.assertIn("idx_tracks_isrc_unique", track_indexes)
            self.assertIn("idx_tracks_isrc_compact_unique", track_indexes)
            self.assertIn("idx_tracks_title", track_indexes)
            self.assertIn("idx_tracks_upc", track_indexes)
            self.assertIn("idx_tracks_genre", track_indexes)
            self.assertIn("idx_tracks_catalog_number", track_indexes)
            self.assertIn("idx_tracks_buma_work_number", track_indexes)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()

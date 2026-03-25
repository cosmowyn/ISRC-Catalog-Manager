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
        contract_template_revision_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(ContractTemplateRevisions)").fetchall()
        }
        contract_template_placeholder_columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(ContractTemplatePlaceholders)"
            ).fetchall()
        }
        contract_template_binding_columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(ContractTemplatePlaceholderBindings)"
            ).fetchall()
        }
        contract_template_draft_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(ContractTemplateDrafts)").fetchall()
        }
        contract_template_snapshot_columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(ContractTemplateResolvedSnapshots)"
            ).fetchall()
        }
        contract_template_artifact_columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(ContractTemplateOutputArtifacts)"
            ).fetchall()
        }
        party_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(Parties)").fetchall()
        }
        party_artist_alias_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(PartyArtistAliases)").fetchall()
        }
        track_audio_derivative_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(TrackAudioDerivatives)").fetchall()
        }
        forensic_export_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(ForensicWatermarkExports)").fetchall()
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
        contract_template_revision_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(ContractTemplateRevisions)").fetchall()
        }
        contract_template_placeholder_indexes = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA index_list(ContractTemplatePlaceholders)"
            ).fetchall()
        }
        contract_template_binding_indexes = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA index_list(ContractTemplatePlaceholderBindings)"
            ).fetchall()
        }
        contract_template_draft_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(ContractTemplateDrafts)").fetchall()
        }
        contract_template_snapshot_indexes = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA index_list(ContractTemplateResolvedSnapshots)"
            ).fetchall()
        }
        contract_template_artifact_indexes = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA index_list(ContractTemplateOutputArtifacts)"
            ).fetchall()
        }
        party_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(Parties)").fetchall()
        }
        party_artist_alias_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(PartyArtistAliases)").fetchall()
        }
        track_audio_derivative_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(TrackAudioDerivatives)").fetchall()
        }
        work_track_link_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(WorkTrackLinks)").fetchall()
        }
        forensic_export_indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(ForensicWatermarkExports)").fetchall()
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
        self.assertIn("PartyArtistAliases", tables)
        self.assertIn("Works", tables)
        self.assertIn("WorkContributors", tables)
        self.assertIn("WorkContributionEntries", tables)
        self.assertIn("WorkTrackLinks", tables)
        self.assertIn("WorkOwnershipInterests", tables)
        self.assertIn("RecordingContributionEntries", tables)
        self.assertIn("RecordingOwnershipInterests", tables)
        self.assertIn("Contracts", tables)
        self.assertIn("ContractParties", tables)
        self.assertIn("ContractObligations", tables)
        self.assertIn("ContractDocuments", tables)
        self.assertIn("ContractTemplates", tables)
        self.assertIn("ContractTemplateRevisions", tables)
        self.assertIn("ContractTemplatePlaceholders", tables)
        self.assertIn("ContractTemplatePlaceholderBindings", tables)
        self.assertIn("ContractTemplateDrafts", tables)
        self.assertIn("ContractTemplateResolvedSnapshots", tables)
        self.assertIn("ContractTemplateOutputArtifacts", tables)
        self.assertIn("RightsRecords", tables)
        self.assertIn("AssetVersions", tables)
        self.assertIn("SavedSearches", tables)
        self.assertIn("AuthenticityKeys", tables)
        self.assertIn("AuthenticityManifests", tables)
        self.assertIn("DerivativeExportBatches", tables)
        self.assertIn("TrackAudioDerivatives", tables)
        self.assertIn("ForensicWatermarkExports", tables)
        self.assertIn("vw_Licenses", tables)
        self.assertIn("contract_number", gs1_columns)
        self.assertTrue(
            {
                "artist_name",
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
            <= party_columns
        )
        self.assertTrue(
            {
                "party_id",
                "alias_name",
                "normalized_alias",
                "sort_order",
                "created_at",
                "updated_at",
            }
            <= party_artist_alias_columns
        )
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
        self.assertTrue(
            {
                "forensic_export_id",
                "batch_id",
                "derivative_export_id",
                "track_id",
                "key_id",
                "token_version",
                "forensic_watermark_version",
                "token_id",
                "binding_crc32",
                "recipient_label",
                "share_label",
                "output_format",
                "output_filename",
                "output_sha256",
                "output_size_bytes",
                "source_lineage_ref",
                "created_at",
                "last_verified_at",
                "last_verification_status",
                "last_verification_confidence",
            }
            <= forensic_export_columns
        )
        self.assertTrue(
            {
                "idx_parties_artist_name",
                "idx_parties_company_name",
                "idx_parties_alternative_email",
                "idx_parties_chamber_of_commerce_number",
                "idx_parties_pro_number",
            }
            <= party_indexes
        )
        self.assertTrue(
            {
                "idx_party_artist_aliases_normalized_alias",
                "idx_party_artist_aliases_party_id",
            }
            <= party_artist_alias_indexes
        )
        self.assertTrue(
            {
                "template_id",
                "source_filename",
                "managed_file_path",
                "storage_mode",
                "source_blob",
                "scan_status",
                "scan_adapter",
                "scan_diagnostics_json",
                "placeholder_inventory_hash",
                "placeholder_count",
            }
            <= contract_template_revision_columns
        )
        self.assertTrue(
            {
                "revision_id",
                "canonical_symbol",
                "binding_kind",
                "namespace",
                "placeholder_key",
                "source_occurrence_count",
            }
            <= contract_template_placeholder_columns
        )
        self.assertTrue(
            {
                "revision_id",
                "placeholder_id",
                "canonical_symbol",
                "resolver_kind",
                "validation_json",
                "metadata_json",
            }
            <= contract_template_binding_columns
        )
        self.assertTrue(
            {
                "revision_id",
                "managed_file_path",
                "storage_mode",
                "payload_blob",
                "filename",
                "last_resolved_snapshot_id",
            }
            <= contract_template_draft_columns
        )
        self.assertTrue(
            {
                "draft_id",
                "revision_id",
                "resolved_values_json",
                "resolution_warnings_json",
                "preview_payload_json",
                "resolved_checksum_sha256",
            }
            <= contract_template_snapshot_columns
        )
        self.assertTrue(
            {
                "snapshot_id",
                "artifact_type",
                "status",
                "output_path",
                "output_filename",
                "retained",
            }
            <= contract_template_artifact_columns
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
                "work_id",
                "parent_track_id",
                "relationship_type",
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
        self.assertIn("idx_tracks_work_id", track_indexes)
        self.assertIn("idx_tracks_parent_track_id", track_indexes)
        self.assertIn("idx_tracks_relationship_type", track_indexes)
        self.assertIn("idx_work_track_links_unique_track", work_track_link_indexes)
        self.assertIn("idx_gs1_metadata_export_enabled", gs1_indexes)
        self.assertIn("idx_gs1_metadata_contract_number", gs1_indexes)
        self.assertIn(
            "idx_contract_template_revisions_template_id",
            contract_template_revision_indexes,
        )
        self.assertIn(
            "idx_contract_template_placeholders_revision_id",
            contract_template_placeholder_indexes,
        )
        self.assertIn(
            "idx_contract_template_bindings_revision_id",
            contract_template_binding_indexes,
        )
        self.assertIn("idx_contract_template_drafts_status", contract_template_draft_indexes)
        self.assertIn(
            "idx_contract_template_snapshots_draft_id",
            contract_template_snapshot_indexes,
        )
        self.assertIn(
            "idx_contract_template_artifacts_snapshot_id",
            contract_template_artifact_indexes,
        )
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
        self.assertIn("idx_forensic_watermark_exports_export_id", forensic_export_indexes)
        self.assertIn(
            "idx_forensic_watermark_exports_token_binding",
            forensic_export_indexes,
        )
        self.assertIn("idx_forensic_watermark_exports_batch_id", forensic_export_indexes)
        self.assertIn(
            "idx_forensic_watermark_exports_derivative_export_id",
            forensic_export_indexes,
        )
        self.assertIn("idx_forensic_watermark_exports_track_id", forensic_export_indexes)
        self.assertIn("idx_forensic_watermark_exports_output_sha256", forensic_export_indexes)
        self.assertIn("idx_forensic_watermark_exports_created_at", forensic_export_indexes)
        self.assertIn("trg_contract_template_revisions_storage_ins", triggers)
        self.assertIn("trg_contract_template_revisions_storage_upd", triggers)
        self.assertIn("trg_contract_template_drafts_storage_ins", triggers)
        self.assertIn("trg_contract_template_drafts_storage_upd", triggers)
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

    def case_migrate_28_to_29_adds_forensic_export_ledger(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 28")
            conn.execute("DROP TABLE IF EXISTS ForensicWatermarkExports")
            conn.commit()

            service.migrate_schema()

            forensic_export_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(ForensicWatermarkExports)").fetchall()
            }
            forensic_export_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(ForensicWatermarkExports)").fetchall()
            }

            self.assertTrue(
                {
                    "forensic_export_id",
                    "batch_id",
                    "derivative_export_id",
                    "track_id",
                    "key_id",
                    "token_version",
                    "forensic_watermark_version",
                    "token_id",
                    "binding_crc32",
                    "recipient_label",
                    "share_label",
                    "output_format",
                    "output_filename",
                    "output_sha256",
                    "output_size_bytes",
                    "source_lineage_ref",
                    "created_at",
                    "last_verified_at",
                    "last_verification_status",
                    "last_verification_confidence",
                }
                <= forensic_export_columns
            )
            self.assertIn("idx_forensic_watermark_exports_export_id", forensic_export_indexes)
            self.assertIn(
                "idx_forensic_watermark_exports_token_binding",
                forensic_export_indexes,
            )
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_29_to_30_adds_contract_template_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 29")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateOutputArtifacts")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateResolvedSnapshots")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateDrafts")
            conn.execute("DROP TABLE IF EXISTS ContractTemplatePlaceholderBindings")
            conn.execute("DROP TABLE IF EXISTS ContractTemplatePlaceholders")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateRevisions")
            conn.execute("DROP TABLE IF EXISTS ContractTemplates")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_revisions_storage_ins")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_revisions_storage_upd")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_drafts_storage_ins")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_drafts_storage_upd")
            conn.commit()

            service.migrate_schema()

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            revision_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(ContractTemplateRevisions)").fetchall()
            }
            draft_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(ContractTemplateDrafts)").fetchall()
            }
            triggers = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
            }

            self.assertTrue(
                {
                    "ContractTemplates",
                    "ContractTemplateRevisions",
                    "ContractTemplatePlaceholders",
                    "ContractTemplatePlaceholderBindings",
                    "ContractTemplateDrafts",
                    "ContractTemplateResolvedSnapshots",
                    "ContractTemplateOutputArtifacts",
                }
                <= tables
            )
            self.assertTrue(
                {
                    "managed_file_path",
                    "storage_mode",
                    "source_blob",
                    "placeholder_inventory_hash",
                    "placeholder_count",
                }
                <= revision_columns
            )
            self.assertTrue(
                {
                    "managed_file_path",
                    "storage_mode",
                    "payload_blob",
                    "last_resolved_snapshot_id",
                }
                <= draft_columns
            )
            self.assertIn("trg_contract_template_revisions_storage_ins", triggers)
            self.assertIn("trg_contract_template_drafts_storage_ins", triggers)
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_30_to_31_adds_contract_template_scan_columns(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA user_version = 30")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_revisions_storage_ins")
            conn.execute("DROP TRIGGER IF EXISTS trg_contract_template_revisions_storage_upd")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateOutputArtifacts")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateResolvedSnapshots")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateDrafts")
            conn.execute("DROP TABLE IF EXISTS ContractTemplatePlaceholderBindings")
            conn.execute("DROP TABLE IF EXISTS ContractTemplatePlaceholders")
            conn.execute("DROP TABLE IF EXISTS ContractTemplateRevisions")
            conn.execute("DROP TABLE IF EXISTS ContractTemplates")
            conn.executescript(
                """
                CREATE TABLE ContractTemplates (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    template_family TEXT NOT NULL DEFAULT 'contract',
                    source_format TEXT,
                    active_revision_id INTEGER,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE ContractTemplateRevisions (
                    id INTEGER PRIMARY KEY,
                    template_id INTEGER NOT NULL,
                    revision_label TEXT,
                    source_filename TEXT NOT NULL,
                    source_mime_type TEXT,
                    source_format TEXT NOT NULL DEFAULT 'docx',
                    source_path TEXT,
                    managed_file_path TEXT,
                    storage_mode TEXT,
                    source_blob BLOB,
                    source_checksum_sha256 TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    scan_status TEXT NOT NULL DEFAULT 'scan_pending',
                    scan_error TEXT,
                    placeholder_inventory_hash TEXT,
                    placeholder_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (template_id) REFERENCES ContractTemplates(id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()

            service.migrate_schema()

            revision_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(ContractTemplateRevisions)").fetchall()
            }

            self.assertTrue({"scan_adapter", "scan_diagnostics_json"} <= revision_columns)
            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
        finally:
            conn.close()

    def case_migrate_31_to_32_adds_party_expansion_and_alias_table(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            service.init_db()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA user_version = 31")
            conn.execute("DROP INDEX IF EXISTS idx_party_artist_aliases_party_id")
            conn.execute("DROP INDEX IF EXISTS idx_party_artist_aliases_normalized_alias")
            conn.execute("DROP TABLE IF EXISTS PartyArtistAliases")
            conn.execute("DROP INDEX IF EXISTS idx_parties_pro_number")
            conn.execute("DROP INDEX IF EXISTS idx_parties_chamber_of_commerce_number")
            conn.execute("DROP INDEX IF EXISTS idx_parties_alternative_email")
            conn.execute("DROP INDEX IF EXISTS idx_parties_company_name")
            conn.execute("DROP INDEX IF EXISTS idx_parties_artist_name")
            conn.execute("DROP TABLE IF EXISTS Parties")
            conn.executescript(
                """
                CREATE TABLE Parties (
                    id INTEGER PRIMARY KEY,
                    legal_name TEXT NOT NULL,
                    display_name TEXT,
                    party_type TEXT NOT NULL DEFAULT 'organization',
                    contact_person TEXT,
                    email TEXT,
                    phone TEXT,
                    website TEXT,
                    address_line1 TEXT,
                    address_line2 TEXT,
                    city TEXT,
                    region TEXT,
                    postal_code TEXT,
                    country TEXT,
                    tax_id TEXT,
                    vat_number TEXT,
                    pro_affiliation TEXT,
                    ipi_cae TEXT,
                    notes TEXT,
                    profile_name TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO Parties(
                    id,
                    legal_name,
                    display_name,
                    party_type,
                    contact_person,
                    email,
                    phone,
                    website,
                    address_line1,
                    city,
                    country,
                    tax_id,
                    vat_number,
                    pro_affiliation,
                    ipi_cae,
                    notes,
                    profile_name
                )
                VALUES (
                    1,
                    'Aeonium Holdings B.V.',
                    'Aeonium',
                    'licensee',
                    'Lyra Contact',
                    'hello@moonium.test',
                    '+31 20 555 0101',
                    'https://moonium.test',
                    'Main Street 12',
                    'Amsterdam',
                    'NL',
                    'TAX-001',
                    'VAT-001',
                    'BUMA',
                    'IPI-001',
                    'Existing note',
                    'default'
                );
                """
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")

            service.migrate_schema()

            party_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(Parties)").fetchall()
            }
            alias_tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            alias_indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(PartyArtistAliases)").fetchall()
            }
            party_row = conn.execute(
                """
                SELECT
                    legal_name,
                    display_name,
                    email,
                    artist_name,
                    company_name,
                    alternative_email,
                    chamber_of_commerce_number,
                    pro_number
                FROM Parties
                WHERE id=1
                """
            ).fetchone()

            self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            self.assertTrue(
                {
                    "artist_name",
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
                <= party_columns
            )
            self.assertIn("PartyArtistAliases", alias_tables)
            self.assertTrue(
                {
                    "idx_party_artist_aliases_normalized_alias",
                    "idx_party_artist_aliases_party_id",
                }
                <= alias_indexes
            )
            self.assertEqual(
                party_row,
                (
                    "Aeonium Holdings B.V.",
                    "Aeonium",
                    "hello@moonium.test",
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        finally:
            conn.close()

    def case_migrate_32_to_33_adds_governance_columns_and_explicit_interest_tables(self):
        conn = sqlite3.connect(":memory:")
        try:
            service = DatabaseSchemaService(conn)
            conn.execute("PRAGMA foreign_keys = OFF")
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
                CREATE TABLE Parties (
                    id INTEGER PRIMARY KEY,
                    legal_name TEXT NOT NULL,
                    display_name TEXT,
                    artist_name TEXT,
                    company_name TEXT,
                    first_name TEXT,
                    middle_name TEXT,
                    last_name TEXT,
                    party_type TEXT NOT NULL DEFAULT 'organization',
                    contact_person TEXT,
                    email TEXT,
                    alternative_email TEXT,
                    phone TEXT,
                    website TEXT,
                    street_name TEXT,
                    street_number TEXT,
                    address_line1 TEXT,
                    address_line2 TEXT,
                    city TEXT,
                    region TEXT,
                    postal_code TEXT,
                    country TEXT,
                    bank_account_number TEXT,
                    chamber_of_commerce_number TEXT,
                    tax_id TEXT,
                    vat_number TEXT,
                    pro_affiliation TEXT,
                    pro_number TEXT,
                    ipi_cae TEXT,
                    notes TEXT,
                    profile_name TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE Works (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    alternate_titles TEXT,
                    version_subtitle TEXT,
                    language TEXT,
                    lyrics_flag INTEGER NOT NULL DEFAULT 0,
                    instrumental_flag INTEGER NOT NULL DEFAULT 0,
                    genre_notes TEXT,
                    iswc TEXT,
                    registration_number TEXT,
                    work_status TEXT,
                    metadata_complete INTEGER NOT NULL DEFAULT 0,
                    contract_signed INTEGER NOT NULL DEFAULT 0,
                    rights_verified INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    profile_name TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE Contracts (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    contract_type TEXT,
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
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    isrc TEXT NOT NULL,
                    isrc_compact TEXT,
                    db_entry_date DATE DEFAULT CURRENT_DATE,
                    audio_file_path TEXT,
                    audio_file_storage_mode TEXT,
                    audio_file_blob BLOB,
                    audio_file_filename TEXT,
                    audio_file_mime_type TEXT,
                    audio_file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    track_title TEXT NOT NULL,
                    catalog_number TEXT,
                    album_art_path TEXT,
                    album_art_storage_mode TEXT,
                    album_art_blob BLOB,
                    album_art_filename TEXT,
                    album_art_mime_type TEXT,
                    album_art_size_bytes INTEGER NOT NULL DEFAULT 0,
                    main_artist_id INTEGER NOT NULL,
                    buma_work_number TEXT,
                    album_id INTEGER,
                    release_date DATE,
                    track_length_sec INTEGER NOT NULL DEFAULT 0,
                    iswc TEXT,
                    upc TEXT,
                    genre TEXT,
                    composer TEXT,
                    publisher TEXT,
                    comments TEXT,
                    lyrics TEXT
                );
                CREATE TABLE WorkContributors (
                    id INTEGER PRIMARY KEY,
                    work_id INTEGER NOT NULL,
                    party_id INTEGER,
                    display_name TEXT,
                    role TEXT NOT NULL,
                    share_percent REAL,
                    role_share_percent REAL,
                    notes TEXT
                );
                CREATE TABLE WorkTrackLinks (
                    work_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    is_primary INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    PRIMARY KEY (work_id, track_id)
                );
                INSERT INTO Artists(id, name) VALUES (1, 'Catalog Artist');
                INSERT INTO Works(id, title) VALUES (1, 'Signal Song'), (2, 'Legacy Parallel Work');
                INSERT INTO Parties(id, legal_name, display_name) VALUES (1, 'Signal Writer', 'Signal Writer');
                INSERT INTO Tracks(
                    id,
                    isrc,
                    isrc_compact,
                    track_title,
                    main_artist_id,
                    buma_work_number
                )
                VALUES
                    (1, 'NL-ABC-26-00001', 'NLABC2600001', 'Signal Song', 1, 'BUMA-001'),
                    (2, 'NL-ABC-26-00002', 'NLABC2600002', 'Signal Song Remix', 1, 'BUMA-002');
                INSERT INTO WorkContributors(
                    id,
                    work_id,
                    party_id,
                    display_name,
                    role,
                    share_percent,
                    role_share_percent,
                    notes
                )
                VALUES (1, 1, 1, 'Signal Writer', 'songwriter', 100.0, 100.0, 'legacy row');
                INSERT INTO WorkTrackLinks(work_id, track_id, is_primary, notes)
                VALUES
                    (1, 1, 1, 'keep this'),
                    (2, 1, 0, 'drop this duplicate'),
                    (1, 2, 0, 'same work second track');
                """
            )
            conn.execute("PRAGMA user_version = 32")
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")

            service.migrate_schema()

            track_columns = {row[1] for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()}
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            work_track_link_indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(WorkTrackLinks)").fetchall()
            }
            governance_rows = conn.execute(
                """
                SELECT id, work_id, parent_track_id, relationship_type
                FROM Tracks
                ORDER BY id
                """
            ).fetchall()
            shadow_rows = conn.execute(
                """
                SELECT work_id, track_id, is_primary
                FROM WorkTrackLinks
                ORDER BY work_id, track_id
                """
            ).fetchall()
            contribution_rows = conn.execute(
                """
                SELECT work_id, party_id, display_name, role, share_percent, role_share_percent, notes
                FROM WorkContributionEntries
                ORDER BY id
                """
            ).fetchall()

            self.assertTrue({"work_id", "parent_track_id", "relationship_type"} <= track_columns)
            self.assertTrue(
                {
                    "WorkContributionEntries",
                    "WorkOwnershipInterests",
                    "RecordingContributionEntries",
                    "RecordingOwnershipInterests",
                }
                <= tables
            )
            self.assertIn("idx_work_track_links_unique_track", work_track_link_indexes)
            self.assertEqual(
                governance_rows,
                [
                    (1, 1, None, "original"),
                    (2, 1, None, "original"),
                ],
            )
            self.assertEqual(shadow_rows, [(1, 1, 1), (1, 2, 0)])
            self.assertEqual(
                contribution_rows,
                [(1, 1, "Signal Writer", "songwriter", 100.0, 100.0, "legacy row")],
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

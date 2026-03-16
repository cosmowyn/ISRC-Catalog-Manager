import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import (
    CatalogAdminService,
    ContractService,
    DatabaseSchemaService,
    LegacyLicenseMigrationService,
    LicenseService,
    PartyService,
    ReleasePayload,
    ReleaseService,
    ReleaseTrackPlacement,
    TrackCreatePayload,
    TrackService,
    WorkContributorPayload,
    WorkPayload,
    WorkService,
)


class LegacyLicenseMigrationServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.license_service = LicenseService(self.conn, self.data_root)
        self.catalog_service = CatalogAdminService(self.conn)
        self.migration_service = LegacyLicenseMigrationService(
            self.conn,
            license_service=self.license_service,
            party_service=self.party_service,
            contract_service=self.contract_service,
            release_service=self.release_service,
            work_service=self.work_service,
        )
        self.source_pdf = self.data_root / "legacy_license.pdf"
        self.source_pdf.write_bytes(b"%PDF-1.4\nlegacy migration test\n")

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _create_track(self, *, isrc: str, title: str) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Migration Artist",
                additional_artists=[],
                album_title="Migration Album",
                release_date="2026-03-16",
                track_length_sec=210,
                iswc=None,
                upc="036000291452",
                genre="Pop",
            )
        )

    def test_migrate_all_promotes_legacy_license_rows_to_contracts(self):
        track_id = self._create_track(isrc="NL-ABC-26-10001", title="Legacy Song")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Migration Album",
                primary_artist="Migration Artist",
                release_type="single",
                release_date="2026-03-16",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Legacy Song",
                contributors=[
                    WorkContributorPayload(role="songwriter", name="Writer One", share_percent=100)
                ],
                track_ids=[track_id],
            )
        )
        self.catalog_service.ensure_licensee("Unused Legacy")
        legacy_record_id = self.license_service.add_license(
            track_id=track_id,
            licensee_name="Legacy Label",
            source_pdf_path=self.source_pdf,
        )
        legacy_record = self.license_service.fetch_license(legacy_record_id)
        self.assertIsNotNone(legacy_record)
        assert legacy_record is not None
        legacy_path = self.license_service.resolve_path(legacy_record.file_path)
        self.assertTrue(legacy_path.exists())

        summary = self.migration_service.inspect()
        self.assertTrue(summary.ready)
        self.assertEqual(summary.legacy_license_count, 1)
        self.assertEqual(summary.legacy_licensee_count, 2)
        self.assertEqual(summary.unused_licensee_count, 1)

        result = self.migration_service.migrate_all()

        self.assertEqual(result.migrated_license_count, 1)
        self.assertEqual(result.migrated_licensee_count, 2)
        self.assertEqual(result.created_contract_count, 1)
        self.assertEqual(result.created_document_count, 1)
        self.assertEqual(result.deleted_legacy_license_count, 1)
        self.assertEqual(result.deleted_legacy_licensee_count, 2)
        self.assertEqual(result.deleted_legacy_file_count, 1)
        self.assertEqual(self.license_service.list_rows(), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Licensees").fetchone()[0],
            0,
        )
        self.assertFalse(legacy_path.exists())

        contracts = self.contract_service.list_contracts()
        self.assertEqual(len(contracts), 1)
        detail = self.contract_service.fetch_contract_detail(contracts[0].id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.track_ids, [track_id])
        self.assertEqual(detail.release_ids, [release_id])
        self.assertEqual(detail.work_ids, [work_id])
        self.assertEqual(len(detail.parties), 1)
        self.assertEqual(detail.parties[0].party_name, "Legacy Label")
        self.assertEqual(len(detail.documents), 1)
        document_path = self.contract_service.resolve_document_path(detail.documents[0].file_path)
        self.assertIsNotNone(document_path)
        assert document_path is not None
        self.assertTrue(document_path.exists())
        self.assertTrue(str(detail.documents[0].file_path).startswith("contract_documents/"))
        self.assertEqual(document_path.read_bytes(), self.source_pdf.read_bytes())

        migrated_parties = self.party_service.list_parties(party_type="licensee")
        self.assertEqual(
            {party.legal_name for party in migrated_parties}, {"Legacy Label", "Unused Legacy"}
        )

    def test_migrate_all_is_blocked_when_legacy_pdf_is_missing(self):
        track_id = self._create_track(isrc="NL-ABC-26-10002", title="Broken Legacy Song")
        legacy_record_id = self.license_service.add_license(
            track_id=track_id,
            licensee_name="Broken Label",
            source_pdf_path=self.source_pdf,
        )
        legacy_record = self.license_service.fetch_license(legacy_record_id)
        self.assertIsNotNone(legacy_record)
        assert legacy_record is not None
        legacy_path = self.license_service.resolve_path(legacy_record.file_path)
        legacy_path.unlink()

        summary = self.migration_service.inspect()
        self.assertFalse(summary.ready)
        self.assertEqual(summary.missing_file_count, 1)

        with self.assertRaises(ValueError):
            self.migration_service.migrate_all()

        self.assertIsNotNone(self.license_service.fetch_license(legacy_record_id))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

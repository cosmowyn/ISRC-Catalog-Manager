import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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


class _FakeMigrationContext:
    def __init__(self):
        self.statuses = []
        self.progress = []
        self.cancelled_checks = 0

    def set_status(self, message):
        self.statuses.append(message)

    def raise_if_cancelled(self):
        self.cancelled_checks += 1

    def report_progress(self, *, value, maximum, message):
        self.progress.append((value, maximum, message))


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

    def test_migrate_all_noops_when_legacy_archive_is_empty(self):
        result = self.migration_service.migrate_all()

        self.assertEqual(result.migrated_license_count, 0)
        self.assertEqual(result.migrated_licensee_count, 0)
        self.assertEqual(result.contract_ids, [])

    def test_migrate_all_reuses_existing_party_and_reports_context_progress(self):
        track_id = self._create_track(isrc="NL-ABC-26-10003", title="Reuse Party Song")
        self.party_service.create_party(
            self.migration_service.party_service_payload("Reusable Label")
        )
        legacy_record_id = self.license_service.add_license(
            track_id=track_id,
            licensee_name="Reusable Label",
            source_pdf_path=self.source_pdf,
        )
        legacy_record = self.license_service.fetch_license(legacy_record_id)
        self.assertIsNotNone(legacy_record)
        assert legacy_record is not None
        legacy_path = self.license_service.resolve_path(legacy_record.file_path)
        ctx = _FakeMigrationContext()

        result = self.migration_service.migrate_all(ctx=ctx)

        self.assertEqual(result.created_party_count, 0)
        self.assertEqual(result.reused_party_count, 1)
        self.assertEqual(result.migrated_license_count, 1)
        self.assertEqual(result.deleted_legacy_file_count, 1)
        self.assertFalse(legacy_path.exists())
        self.assertGreaterEqual(ctx.cancelled_checks, 2)
        self.assertIn("Preparing parties for legacy license migration...", ctx.statuses)
        self.assertTrue(
            any("Migrating legacy license" in status for status in ctx.statuses),
            ctx.statuses,
        )
        self.assertTrue(
            any(progress[2] == "Prepared legacy licensee parties." for progress in ctx.progress),
            ctx.progress,
        )
        self.assertTrue(
            any(
                progress[2] == "Verifying migrated contracts and cleaning legacy data..."
                for progress in ctx.progress
            ),
            ctx.progress,
        )

    def test_migrate_all_cleans_unused_licensees_when_no_license_rows_remain(self):
        self.catalog_service.ensure_licensee("Only Legacy Contact")
        ctx = _FakeMigrationContext()

        result = self.migration_service.migrate_all(ctx=ctx)

        self.assertEqual(result.migrated_license_count, 0)
        self.assertEqual(result.migrated_licensee_count, 1)
        self.assertEqual(result.created_party_count, 1)
        self.assertEqual(result.deleted_legacy_license_count, 0)
        self.assertEqual(result.deleted_legacy_licensee_count, 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Licenses").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Licensees").fetchone()[0], 0)
        self.assertTrue(ctx.progress)

    def test_inspect_reports_missing_track_and_unmanaged_file_with_minimal_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT);
            CREATE TABLE Licensees(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE Licenses(
                id INTEGER PRIMARY KEY,
                track_id INTEGER,
                licensee_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TEXT
            );
            INSERT INTO Licensees(id, name) VALUES (1, 'Missing Track'), (2, 'External');
            INSERT INTO Licenses(id, track_id, licensee_id, file_path, filename, uploaded_at)
            VALUES
                (10, NULL, 1, 'missing.pdf', 'missing.pdf', '2026-04-01T12:34:00'),
                (11, 99, 2, 'external.pdf', 'external.pdf', 'short');
            """)
        external_pdf = self.data_root / "outside.pdf"
        external_pdf.write_bytes(b"external")
        license_service = SimpleNamespace(
            resolve_path=mock.Mock(
                side_effect=lambda stored_path: (
                    external_pdf if stored_path == "external.pdf" else self.data_root / stored_path
                )
            ),
            is_managed_license_path=mock.Mock(return_value=False),
        )
        service = LegacyLicenseMigrationService(
            conn,
            license_service=license_service,
            party_service=mock.Mock(),
            contract_service=mock.Mock(),
        )

        summary = service.inspect()

        self.assertFalse(summary.ready)
        self.assertEqual(summary.legacy_license_count, 2)
        self.assertEqual(summary.missing_track_count, 1)
        self.assertEqual(summary.missing_file_count, 1)
        self.assertEqual(summary.unmanaged_file_count, 1)
        self.assertEqual(
            {issue.code for issue in summary.issues},
            {"missing_track", "missing_file", "unmanaged_file"},
        )
        conn.close()

    def test_blocked_migration_reports_truncated_issue_list(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT);
            CREATE TABLE Licensees(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE Licenses(
                id INTEGER PRIMARY KEY,
                track_id INTEGER,
                licensee_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TEXT
            );
            INSERT INTO Licensees(id, name) VALUES (1, 'Broken Batch');
        """)
        conn.executemany(
            """
            INSERT INTO Licenses(id, track_id, licensee_id, file_path, filename, uploaded_at)
            VALUES (?, NULL, 1, ?, ?, '2026-05-01T12:00:00')
            """,
            [(index, f"missing-{index}.pdf", f"missing-{index}.pdf") for index in range(1, 13)],
        )
        license_service = SimpleNamespace(
            resolve_path=mock.Mock(side_effect=lambda stored_path: self.data_root / stored_path),
            is_managed_license_path=mock.Mock(return_value=True),
        )
        service = LegacyLicenseMigrationService(
            conn,
            license_service=license_service,
            party_service=mock.Mock(),
            contract_service=mock.Mock(),
        )

        with self.assertRaisesRegex(ValueError, r"\.\.\.and 14 more issue\(s\)\."):
            service.migrate_all()
        conn.close()

    def test_migrate_all_detects_post_create_contract_integrity_failures(self):
        old_path = self.data_root / "legacy-integrity.pdf"
        old_path.write_bytes(b"legacy integrity bytes")
        old_checksum = LegacyLicenseMigrationService._hash_file(old_path)
        new_path = self.data_root / "contract_documents" / "migrated-integrity.pdf"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(b"legacy integrity bytes")
        changed_path = self.data_root / "contract_documents" / "changed-integrity.pdf"
        changed_path.write_bytes(b"changed bytes")
        changed_checksum = LegacyLicenseMigrationService._hash_file(changed_path)

        scenarios = [
            (
                "not be reloaded",
                SimpleNamespace(fetch_contract_detail=mock.Mock(return_value=None)),
            ),
            (
                "not be reloaded",
                SimpleNamespace(
                    fetch_contract_detail=mock.Mock(return_value=SimpleNamespace(documents=[]))
                ),
            ),
            (
                "missing-document.pdf",
                SimpleNamespace(
                    fetch_contract_detail=mock.Mock(
                        return_value=SimpleNamespace(
                            documents=[
                                SimpleNamespace(
                                    file_path="missing-document.pdf",
                                    checksum_sha256=old_checksum,
                                )
                            ]
                        )
                    ),
                    resolve_document_path=mock.Mock(
                        return_value=self.data_root / "contract_documents" / "missing.pdf"
                    ),
                ),
            ),
            (
                "checksum mismatch",
                SimpleNamespace(
                    fetch_contract_detail=mock.Mock(
                        return_value=SimpleNamespace(
                            documents=[
                                SimpleNamespace(
                                    file_path="migrated-integrity.pdf",
                                    checksum_sha256="not-the-real-checksum",
                                )
                            ]
                        )
                    ),
                    resolve_document_path=mock.Mock(return_value=new_path),
                ),
            ),
            (
                "content mismatch",
                SimpleNamespace(
                    fetch_contract_detail=mock.Mock(
                        return_value=SimpleNamespace(
                            documents=[
                                SimpleNamespace(
                                    file_path="changed-integrity.pdf",
                                    checksum_sha256=changed_checksum,
                                )
                            ]
                        )
                    ),
                    resolve_document_path=mock.Mock(return_value=changed_path),
                ),
            ),
        ]

        for expected_message, contract_service in scenarios:
            conn = sqlite3.connect(":memory:")
            conn.executescript("""
                CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT);
                CREATE TABLE Licensees(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE Licenses(
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER,
                    licensee_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    uploaded_at TEXT
                );
                INSERT INTO Tracks(id, track_title) VALUES (5, 'Integrity Track');
                INSERT INTO Licensees(id, name) VALUES (7, 'Integrity Label');
                INSERT INTO Licenses(id, track_id, licensee_id, file_path, filename, uploaded_at)
                VALUES (11, 5, 7, 'legacy-integrity.pdf', 'legacy-integrity.pdf', NULL);
            """)
            conn.commit()
            contract_service.create_contract = mock.Mock(return_value=101)
            contract_service.resolve_document_path = getattr(
                contract_service,
                "resolve_document_path",
                mock.Mock(return_value=new_path),
            )
            service = LegacyLicenseMigrationService(
                conn,
                license_service=SimpleNamespace(
                    resolve_path=mock.Mock(return_value=old_path),
                    is_managed_license_path=mock.Mock(return_value=True),
                ),
                party_service=SimpleNamespace(
                    find_party_id_by_name=mock.Mock(return_value=42),
                    create_party=mock.Mock(side_effect=AssertionError("should reuse party")),
                ),
                contract_service=contract_service,
            )

            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(Exception, expected_message):
                    service.migrate_all()
            conn.close()

    def test_helper_cleanup_and_restore_paths_are_idempotent(self):
        legacy_path = self.data_root / "licenses" / "restored.pdf"
        migrated_doc = self.data_root / "contract_documents" / "migrated.pdf"
        migrated_doc.parent.mkdir(parents=True, exist_ok=True)
        migrated_doc.write_bytes(b"restored bytes")
        cleanup_doc = self.data_root / "contract_documents" / "cleanup.pdf"
        cleanup_doc.write_bytes(b"cleanup bytes")

        contract_service = mock.Mock()
        contract_service.resolve_document_path.side_effect = lambda stored_path: {
            "cleanup.pdf": cleanup_doc,
            "migrated.pdf": migrated_doc,
            "missing.pdf": self.data_root / "contract_documents" / "missing.pdf",
            "none": None,
            "bad-unlink": mock.Mock(unlink=mock.Mock(side_effect=OSError("locked"))),
        }.get(stored_path)
        license_service = mock.Mock(
            resolve_path=mock.Mock(
                side_effect=lambda stored_path: {
                    "restored.pdf": legacy_path,
                    "already.pdf": migrated_doc,
                }[stored_path]
            )
        )
        service = LegacyLicenseMigrationService(
            self.conn,
            license_service=license_service,
            party_service=self.party_service,
            contract_service=contract_service,
        )

        self.assertEqual(service._legacy_received_date("2026-04-05T10:11:12"), "2026-04-05")
        self.assertIsNone(service._legacy_received_date("short"))
        self.assertEqual(service._work_ids_for_track(None), [])
        self.assertEqual(service._release_ids_for_track(None), [])

        service._cleanup_new_documents(["cleanup.pdf", "cleanup.pdf", "", "none", "bad-unlink"])
        self.assertFalse(cleanup_doc.exists())

        service._restore_legacy_files(
            [
                ("restored.pdf", "migrated.pdf"),
                ("already.pdf", "migrated.pdf"),
                ("restored.pdf", "missing.pdf"),
                ("restored.pdf", "none"),
            ]
        )
        self.assertEqual(legacy_path.read_bytes(), b"restored bytes")


if __name__ == "__main__":
    unittest.main()

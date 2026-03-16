import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class WorkAndPartyServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(self, isrc: str, title: str) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Catalog Artist",
                additional_artists=[],
                album_title="Catalog Album",
                release_date="2026-03-16",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Alt",
            )
        )

    def test_work_creation_links_tracks_and_creates_party_records(self):
        track_id = self._create_track("NL-ABC-26-00001", "Night Drive")

        work_id = self.work_service.create_work(
            WorkPayload(
                title="Night Drive",
                iswc="T-123.456.789-0",
                contributors=[
                    WorkContributorPayload(role="songwriter", name="Alex Writer", share_percent=50),
                    WorkContributorPayload(
                        role="composer",
                        name="Jamie Composer",
                        share_percent=50,
                    ),
                    WorkContributorPayload(role="publisher", name="Moonlight Publishing"),
                ],
                track_ids=[track_id],
                work_status="metadata_incomplete",
            )
        )

        detail = self.work_service.fetch_work_detail(work_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.track_ids, [track_id])
        self.assertEqual(len(detail.contributors), 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 3)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM WorkTrackLinks WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            1,
        )

    def test_work_validation_flags_invalid_split_totals_and_duplicate_iswc(self):
        self.work_service.create_work(
            WorkPayload(
                title="Existing Work",
                iswc="T-999.111.222-3",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Existing Writer",
                        share_percent=100,
                    )
                ],
            )
        )

        issues = self.work_service.validate_work(
            WorkPayload(
                title="Conflicting Work",
                iswc="T-999.111.222-3",
                contributors=[
                    WorkContributorPayload(role="songwriter", name="Writer A", share_percent=25),
                    WorkContributorPayload(role="composer", name="Writer B", share_percent=25),
                ],
            )
        )

        self.assertTrue(any(issue.field_name == "iswc" for issue in issues))
        self.assertTrue(any(issue.field_name == "share_percent" for issue in issues))

    def test_work_duplicate_update_listing_and_primary_track_reassignment(self):
        first_track_id = self._create_track("NL-ABC-26-00011", "Signal Song")
        second_track_id = self._create_track("NL-ABC-26-00012", "Signal Song Acoustic")
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Signal Song",
                iswc="T-444.555.666-7",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Signal Writer",
                        share_percent=100,
                    )
                ],
                track_ids=[first_track_id],
                work_status="idea",
            )
        )

        duplicate_id = self.work_service.duplicate_work(work_id)
        duplicate = self.work_service.fetch_work_detail(duplicate_id)
        assert duplicate is not None
        self.assertEqual(duplicate.work.title, "Signal Song (Copy)")
        self.assertIsNone(duplicate.work.iswc)

        self.work_service.update_work(
            work_id,
            WorkPayload(
                title="Signal Song",
                alternate_titles=["Signal Anthem"],
                version_subtitle="Radio Mix",
                iswc="T-444.555.666-7",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Signal Writer",
                        share_percent=50,
                        role_share_percent=50,
                    ),
                    WorkContributorPayload(
                        role="composer",
                        name="Signal Composer",
                        share_percent=50,
                        role_share_percent=50,
                    ),
                ],
                track_ids=[first_track_id, second_track_id],
                work_status="contract_pending",
            ),
        )

        listed = self.work_service.list_works(
            search_text="Signal Anthem",
            status="contract pending",
            linked_track_id=second_track_id,
        )
        self.assertEqual([item.id for item in listed], [work_id])

        self.work_service.unlink_track(work_id, first_track_id)
        remaining_links = self.conn.execute(
            """
            SELECT track_id, is_primary
            FROM WorkTrackLinks
            WHERE work_id=?
            ORDER BY track_id
            """,
            (work_id,),
        ).fetchall()
        self.assertEqual(remaining_links, [(second_track_id, 1)])

        exported = self.work_service.export_rows()
        exported_work = next(row for row in exported if row["id"] == work_id)
        self.assertEqual(exported_work["track_ids"], [second_track_id])
        self.assertEqual(len(exported_work["contributors"]), 2)

    def test_party_duplicate_detection_merge_usage_summary_and_filters(self):
        primary_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Music BV",
                display_name="Signal Music",
                email="info@signal.test",
                ipi_cae="IPI-001",
            )
        )
        duplicate_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Music BV",
                email="other@signal.test",
            )
        )
        cursor = self.conn.execute(
            """
            INSERT INTO Parties (legal_name, email, ipi_cae, party_type)
            VALUES (?, ?, ?, ?)
            """,
            ("Signal Rights BV", "info@signal.test", "IPI-002", "organization"),
        )
        mirrored_email_id = int(cursor.lastrowid)
        reused_id = self.party_service.ensure_party_by_name("Signal Music")
        self.assertEqual(reused_id, primary_id)

        work_id = self.work_service.create_work(
            WorkPayload(
                title="Signal Song",
                contributors=[
                    WorkContributorPayload(
                        role="publisher",
                        name="Signal Music BV",
                        party_id=duplicate_id,
                    )
                ],
            )
        )
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Signal Deal",
                parties=[
                    ContractPartyPayload(party_id=duplicate_id, role_label="publisher"),
                ],
            )
        )
        right_id = self.rights_service.create_right(
            RightPayload(
                title="Signal Right",
                right_type="master",
                granted_to_party_id=duplicate_id,
                track_id=self._create_track("NL-ABC-26-00013", "Signal Rights"),
            )
        )
        self.assertGreater(contract_id, 0)
        self.assertGreater(right_id, 0)

        duplicates = self.party_service.detect_duplicates()
        duplicate_types = {item.match_type for item in duplicates}
        self.assertIn("legal_name", duplicate_types)
        self.assertIn("email", duplicate_types)

        listed = self.party_service.list_parties(
            search_text="signal",
            party_type="organization",
        )
        self.assertTrue(any(item.id == primary_id for item in listed))

        usage_before_merge = self.party_service.usage_summary(duplicate_id)
        self.assertEqual(usage_before_merge.work_count, 1)
        self.assertEqual(usage_before_merge.contract_count, 1)
        self.assertEqual(usage_before_merge.rights_count, 1)

        merged = self.party_service.merge_parties(primary_id, [duplicate_id, mirrored_email_id])
        self.assertEqual(merged.id, primary_id)
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM WorkContributors WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM ContractParties WHERE contract_id=?",
                (contract_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT granted_to_party_id FROM RightsRecords WHERE id=?",
                (right_id,),
            ).fetchone()[0],
            primary_id,
        )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.parties import PartyPayload, PartyService
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
                        role="composer", name="Jamie Composer", share_percent=50
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
                "SELECT COUNT(*) FROM WorkTrackLinks WHERE work_id=?", (work_id,)
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
                        role="songwriter", name="Existing Writer", share_percent=100
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

    def test_party_duplicate_detection_and_merge_updates_links(self):
        left_id = self.party_service.create_party(
            PartyPayload(legal_name="Signal Music BV", email="info@signal.test")
        )
        right_id = self.party_service.create_party(
            PartyPayload(legal_name="Signal Music BV", email="other@signal.test")
        )
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Signal Song",
                contributors=[
                    WorkContributorPayload(
                        role="publisher", name="Signal Music BV", party_id=right_id
                    )
                ],
            )
        )
        self.assertGreater(work_id, 0)

        duplicates = self.party_service.detect_duplicates()
        self.assertTrue(any(item.match_type == "legal_name" for item in duplicates))

        merged = self.party_service.merge_parties(left_id, [right_id])
        self.assertEqual(merged.id, left_id)
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM WorkContributors WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            left_id,
        )


if __name__ == "__main__":
    unittest.main()

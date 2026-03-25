import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import (
    DatabaseSchemaService,
    RepertoireWorkflowService,
    TrackCreatePayload,
    TrackService,
)
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class RepertoireWorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.workflow_service = RepertoireWorkflowService(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _seed_repertoire(self) -> tuple[int, int, int]:
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00123",
                track_title="Workflow Song",
                artist_name="Workflow Artist",
                additional_artists=[],
                album_title="Workflow Release",
                release_date="2026-03-16",
                track_length_sec=203,
                iswc=None,
                upc="036000291452",
                genre="Pop",
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Workflow Release",
                primary_artist="Workflow Artist",
                release_type="single",
                release_date="2026-03-16",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        party_id = self.party_service.create_party(PartyPayload(legal_name="Workflow Writer"))
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Workflow Song",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Workflow Writer",
                        party_id=party_id,
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )
        return work_id, track_id, release_id

    def test_bulk_status_updates_and_readiness_snapshots(self):
        work_id, track_id, release_id = self._seed_repertoire()

        updated_tracks = self.workflow_service.set_track_status(
            [track_id, track_id, -1],
            status="Rights Verified",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
        )
        updated_works = self.workflow_service.set_work_status(
            [work_id],
            status="unknown future state",
            metadata_complete=True,
            contract_signed=True,
        )
        updated_releases = self.workflow_service.set_release_status(
            [release_id],
            status="Final Master Received",
            metadata_complete=True,
            rights_verified=True,
        )

        self.assertEqual(updated_tracks, 1)
        self.assertEqual(updated_works, 1)
        self.assertEqual(updated_releases, 1)
        self.assertEqual(
            self.conn.execute("SELECT work_status FROM Works WHERE id=?", (work_id,)).fetchone()[0],
            "metadata_incomplete",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT repertoire_status FROM Tracks WHERE id=?",
                (track_id,),
            ).fetchone()[0],
            "rights_verified",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT repertoire_status FROM Releases WHERE id=?",
                (release_id,),
            ).fetchone()[0],
            "final_master_received",
        )

        self.conn.execute(
            "UPDATE Tracks SET audio_file_path='track_media/audio/workflow.wav' WHERE id=?",
            (track_id,),
        )
        self.conn.execute(
            "UPDATE Releases SET artwork_path='release_media/images/workflow.png' WHERE id=?",
            (release_id,),
        )

        work_snapshot = self.workflow_service.readiness_snapshot("work", work_id)
        track_snapshot = self.workflow_service.readiness_snapshot("track", track_id)
        release_snapshot = self.workflow_service.readiness_snapshot("release", release_id)

        self.assertEqual(
            work_snapshot,
            {
                "metadata_complete": True,
                "contract_signed": True,
                "rights_verified": False,
                "creator_linked": True,
            },
        )
        self.assertEqual(
            track_snapshot,
            {
                "metadata_complete": True,
                "contract_signed": True,
                "rights_verified": True,
                "audio_attached": True,
                "work_linked": True,
            },
        )
        self.assertEqual(
            release_snapshot,
            {
                "metadata_complete": True,
                "contract_signed": False,
                "rights_verified": True,
                "artwork_present": True,
                "has_tracks": True,
            },
        )

        summary = self.workflow_service.summary_counts()
        self.assertEqual(summary["works"]["metadata_incomplete"], 1)
        self.assertEqual(summary["tracks"]["rights_verified"], 1)
        self.assertEqual(summary["releases"]["final_master_received"], 1)

    def test_bulk_update_noops_when_no_assignments_are_provided(self):
        work_id, _track_id, _release_id = self._seed_repertoire()

        self.assertEqual(self.workflow_service.set_work_status([work_id]), 0)
        self.assertEqual(self.workflow_service.set_track_status([], status="cleared"), 0)
        self.assertEqual(self.workflow_service.readiness_snapshot("unknown", 1), {})

    def test_track_readiness_prefers_direct_work_id_over_shadow_link_rows(self):
        work_id, track_id, _release_id = self._seed_repertoire()

        self.conn.execute(
            "DELETE FROM WorkTrackLinks WHERE work_id=? AND track_id=?",
            (work_id, track_id),
        )

        snapshot = self.workflow_service.readiness_snapshot("track", track_id)

        self.assertTrue(snapshot["work_linked"])


if __name__ == "__main__":
    unittest.main()

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.quality import QualityDashboardService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import (
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)


class QualityDashboardServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.custom_defs = CustomFieldDefinitionService(self.conn)
        self.service = QualityDashboardService(
            self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            data_root=self.data_root,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(self, *, isrc: str = "", title: str = "Orbit", album: str | None = "Orbit Release") -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Cosmowyn",
                additional_artists=[],
                album_title=album,
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
                buma_work_number=None,
                composer=None,
                publisher=None,
                comments=None,
                lyrics=None,
                audio_file_source_path=None,
                album_art_source_path=None,
            )
        )

    def test_scan_reports_expected_issues(self):
        track_id = self._create_track(isrc="")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Cosmowyn",
                release_type="album",
                release_date="2026-03-15",
                upc=None,
                placements=[ReleaseTrackPlacement(track_id=track_id, disc_number=1, track_number=1, sequence_number=1)],
            )
        )
        self.conn.execute(
            "UPDATE Releases SET artwork_path='release_media/images/missing.png' WHERE id=?",
            (release_id,),
        )
        self.conn.execute(
            "UPDATE Tracks SET audio_file_path='track_media/audio/missing.wav' WHERE id=?",
            (track_id,),
        )
        field = self.custom_defs.ensure_fields(
            [{"name": "Mood", "field_type": "text", "options": json.dumps({"required": True})}]
        )[0]
        self.assertIsNotNone(field)

        result = self.service.scan()
        issue_types = {issue.issue_type for issue in result.issues}

        self.assertIn("missing_isrc", issue_types)
        self.assertIn("missing_release_upc", issue_types)
        self.assertIn("broken_media_reference", issue_types)
        self.assertIn("broken_release_artwork_reference", issue_types)
        self.assertIn("missing_required_custom_field", issue_types)

    def test_normalize_dates_fix_updates_invalid_values(self):
        track_id = self._create_track(isrc="NL-ABC-26-00001")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")
        self.conn.execute("UPDATE Tracks SET release_date='15/03/2026' WHERE id=?", (track_id,))
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Cosmowyn",
                release_type="album",
                release_date="15-03-2026",
                placements=[ReleaseTrackPlacement(track_id=track_id, disc_number=1, track_number=1, sequence_number=1)],
            )
        )
        self.assertGreater(release_id, 0)

        message = self.service.apply_fix("normalize_dates")

        self.assertIn("Normalized", message)
        self.assertEqual(
            self.conn.execute("SELECT release_date FROM Tracks WHERE id=?", (track_id,)).fetchone()[0],
            "2026-03-15",
        )
        self.assertEqual(
            self.conn.execute("SELECT release_date FROM Releases WHERE id=?", (release_id,)).fetchone()[0],
            "2026-03-15",
        )

    def test_fill_from_release_populates_blank_track_fields(self):
        track_id = self._create_track(isrc="NL-ABC-26-00002")
        self.conn.execute(
            """
            UPDATE Tracks
            SET release_date='', upc='', catalog_number='', album_id=NULL
            WHERE id=?
            """,
            (track_id,),
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Cosmowyn",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-777",
                upc="036000291452",
                placements=[ReleaseTrackPlacement(track_id=track_id, disc_number=1, track_number=1, sequence_number=1)],
            )
        )
        self.assertGreater(release_id, 0)

        message = self.service.apply_fix("fill_from_release")
        row = self.conn.execute(
            "SELECT release_date, upc, catalog_number, album_id FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()

        self.assertIn("Filled blank track values", message)
        self.assertEqual(row[0], "2026-03-15")
        self.assertEqual(row[1], "036000291452")
        self.assertEqual(row[2], "CAT-777")
        self.assertIsNotNone(row[3])

    def test_same_title_duplicate_upc_is_reported_as_info_not_error(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist One",
                upc="8720892724625",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist Two",
                upc="8720892724625",
            )
        )

        result = self.service.scan()
        shared_upc_issues = [issue for issue in result.issues if issue.issue_type == "shared_release_upc"]

        self.assertEqual(len(shared_upc_issues), 2)
        self.assertTrue(all(issue.severity == "info" for issue in shared_upc_issues))
        self.assertFalse(any(issue.issue_type == "duplicate_release_upc" for issue in result.issues))

    def test_different_title_duplicate_upc_remains_error(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Release One",
                primary_artist="Artist One",
                upc="8720892724625",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Release Two",
                primary_artist="Artist Two",
                upc="8720892724625",
            )
        )

        result = self.service.scan()
        duplicate_upc_issues = [issue for issue in result.issues if issue.issue_type == "duplicate_release_upc"]

        self.assertEqual(len(duplicate_upc_issues), 2)
        self.assertTrue(all(issue.severity == "error" for issue in duplicate_upc_issues))


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.parties import PartyService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.works import WorkPayload, WorkService


class GovernedTrackCreationServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        schema = DatabaseSchemaService(self.conn)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(
            self.conn,
            self.data_root,
            require_governed_creation=True,
        )
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.service = GovernedImportCoordinator(
            self.conn,
            track_service=self.track_service,
            party_service=self.party_service,
            work_service=self.work_service,
            profile_name="governed-test.db",
        )

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_create_governed_track_creates_work_and_seeds_metadata(self):
        result = self.service.create_governed_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-02001",
                track_title="Seeded Anthem",
                artist_name="Aurora Echo",
                additional_artists=["Guest Voice"],
                album_title="Seeded Album",
                release_date="2026-03-26",
                track_length_sec=215,
                iswc="T-123.456.789-0",
                upc="123456789012",
                genre="Ambient",
                buma_work_number="BUMA-123",
                composer="Alex Writer",
                publisher="North Harbor Publishing",
                comments="Imported governed note",
                lyrics="Seeded lyric fragment",
            ),
            governance_mode="create_new_work",
            profile_name="governed-test.db",
        )

        self.assertGreater(result.track_id, 0)
        self.assertIsNotNone(result.created_work_id)
        self.assertEqual(result.work_id, result.created_work_id)
        track_row = self.conn.execute(
            """
            SELECT t.work_id, t.track_title, t.iswc, t.buma_work_number, p.artist_name
            FROM Tracks t
            JOIN Parties p ON p.id = t.main_artist_party_id
            WHERE t.id=?
            """,
            (result.track_id,),
        ).fetchone()
        work_row = self.conn.execute(
            """
            SELECT title, iswc, registration_number, profile_name, genre_notes, notes, lyrics_flag
            FROM Works
            WHERE id=?
            """,
            (result.work_id,),
        ).fetchone()
        contributors = self.conn.execute(
            """
            SELECT role, COALESCE(display_name, '')
            FROM WorkContributors
            WHERE work_id=?
            ORDER BY role, id
            """,
            (result.work_id,),
        ).fetchall()

        self.assertEqual(
            track_row,
            (
                result.work_id,
                "Seeded Anthem",
                "T-123.456.789-0",
                "BUMA-123",
                "Aurora Echo",
            ),
        )
        self.assertEqual(
            work_row,
            (
                "Seeded Anthem",
                "T-123.456.789-0",
                "BUMA-123",
                "governed-test.db",
                "Ambient",
                "Imported governed note",
                1,
            ),
        )
        self.assertIsNotNone(self.party_service.find_artist_party_id_by_name("Aurora Echo"))
        self.assertEqual(
            contributors,
            [
                ("composer", "Alex Writer"),
                ("publisher", "North Harbor Publishing"),
            ],
        )
        additional_artists = self.conn.execute(
            """
            SELECT p.artist_name
            FROM TrackArtists ta
            JOIN Parties p ON p.id = ta.party_id
            WHERE ta.track_id=?
            ORDER BY p.artist_name
            """,
            (result.track_id,),
        ).fetchall()
        self.assertEqual(additional_artists, [("Guest Voice",)])
        self.assertIsNotNone(self.party_service.find_artist_party_id_by_name("Guest Voice"))

    def test_create_governed_track_requires_existing_work_for_link_mode(self):
        with self.assertRaisesRegex(ValueError, "existing Work selection"):
            self.service.create_governed_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-02002",
                    track_title="Missing Link",
                    artist_name="Aurora Echo",
                    additional_artists=[],
                    album_title="Seeded Album",
                    release_date="2026-03-26",
                    track_length_sec=215,
                    iswc=None,
                    upc=None,
                    genre="Ambient",
                ),
                governance_mode="link_existing_work",
            )

    def test_match_or_create_work_reuses_unique_existing_work(self):
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Matched Anthem",
                iswc="T-111.222.333-4",
            )
        )

        result = self.service.create_governed_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-02003",
                track_title="Matched Anthem",
                artist_name="Aurora Echo",
                additional_artists=[],
                album_title="Seeded Album",
                release_date="2026-03-26",
                track_length_sec=215,
                iswc="T-111.222.333-4",
                upc=None,
                genre="Ambient",
            ),
            governance_mode="match_or_create_work",
        )

        self.assertEqual(result.work_id, work_id)
        self.assertIsNone(result.created_work_id)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0],
            1,
        )

    def test_create_governed_track_with_audio_creates_primary_asset_version(self):
        audio_path = self.data_root / "governed-master.wav"
        audio_path.write_bytes(b"RIFFgovernedmaster")

        result = self.service.create_governed_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-02004",
                track_title="Governed Asset Song",
                artist_name="Aurora Echo",
                additional_artists=[],
                album_title="Governed Album",
                release_date="2026-03-26",
                track_length_sec=215,
                iswc=None,
                upc=None,
                genre="Ambient",
                audio_file_source_path=str(audio_path),
                audio_file_storage_mode="database",
            ),
            governance_mode="create_new_work",
        )

        assets = self.track_service.asset_service.list_assets(track_id=result.track_id)
        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset.asset_type, "main_master")
        self.assertTrue(asset.primary_flag)
        self.assertTrue(asset.approved_for_use)
        self.assertEqual(asset.storage_mode, "database")


if __name__ == "__main__":
    unittest.main()

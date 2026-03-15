import sqlite3
import unittest

from isrc_manager.services import TrackCreatePayload, TrackService, TrackUpdatePayload


def make_track_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
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
            db_entry_date TEXT,
            isrc TEXT NOT NULL,
            isrc_compact TEXT,
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
            genre TEXT,
            FOREIGN KEY (main_artist_id) REFERENCES Artists(id) ON DELETE RESTRICT,
            FOREIGN KEY (album_id) REFERENCES Albums(id) ON DELETE SET NULL
        );
        CREATE TABLE TrackArtists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'additional',
            PRIMARY KEY (track_id, artist_id, role),
            FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
            FOREIGN KEY (artist_id) REFERENCES Artists(id) ON DELETE RESTRICT
        );
        """
    )
    return conn


class TrackServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_track_conn()
        self.service = TrackService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_track_persists_relations_and_metadata(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="First Song",
                artist_name="Main Artist",
                additional_artists=["Guest One", "Guest Two"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc="T-123.456.789-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-77",
            )
        )

        row = self.conn.execute(
            """
            SELECT t.isrc, t.isrc_compact, t.track_title, a.name, al.title, t.release_date, t.track_length_sec, t.iswc, t.upc, t.genre, t.catalog_number, t.buma_work_number
            FROM Tracks t
            JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id = ?
            """,
            (track_id,),
        ).fetchone()
        additional = self.conn.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id = ?
            ORDER BY a.name
            """,
            (track_id,),
        ).fetchall()

        self.assertEqual(
            row,
            (
                "NL-ABC-26-00001",
                "NLABC2600001",
                "First Song",
                "Main Artist",
                "Debut Album",
                "2026-03-13",
                245,
                "T-123.456.789-0",
                "123456789012",
                "Pop",
                "CAT-001",
                "BUMA-77",
            ),
        )
        self.assertEqual([name for (name,) in additional], ["Guest One", "Guest Two"])
        self.assertEqual(self.service.fetch_track_title(track_id), "First Song")

    def test_update_track_replaces_track_and_additional_artist_data(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="First Song",
                artist_name="Main Artist",
                additional_artists=["Guest One", "Guest Two"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00002",
                track_title="Second Song",
                artist_name="Renamed Artist",
                additional_artists=["New Guest"],
                album_title="Second Album",
                release_date="2026-03-14",
                track_length_sec=300,
                iswc="T-123.456.789-0",
                upc="1234567890123",
                genre="Electronic",
                catalog_number="CAT-002",
                buma_work_number="BUMA-88",
            )
        )

        row = self.conn.execute(
            """
            SELECT t.isrc, t.isrc_compact, t.track_title, a.name, al.title, t.release_date, t.track_length_sec, t.iswc, t.upc, t.genre, t.catalog_number, t.buma_work_number
            FROM Tracks t
            JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id = ?
            """,
            (track_id,),
        ).fetchone()
        additional = self.conn.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id = ?
            ORDER BY a.name
            """,
            (track_id,),
        ).fetchall()

        self.assertEqual(
            row,
            (
                "NL-ABC-26-00002",
                "NLABC2600002",
                "Second Song",
                "Renamed Artist",
                "Second Album",
                "2026-03-14",
                300,
                "T-123.456.789-0",
                "1234567890123",
                "Electronic",
                "CAT-002",
                "BUMA-88",
            ),
        )
        self.assertEqual([name for (name,) in additional], ["New Guest"])
        self.assertTrue(self.service.is_isrc_taken_normalized("nlabc2600002"))
        self.assertFalse(self.service.is_isrc_taken_normalized("NL-ABC-26-99999"))

    def test_list_album_group_track_ids_skips_blank_and_single_groups(self):
        album_track_a = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00010",
                track_title="Album Track A",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        album_track_b = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00011",
                track_title="Album Track B",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        single_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00012",
                track_title="Single Track",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Single",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        blank_album_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00013",
                track_title="Loose Track",
                artist_name="Main Artist",
                additional_artists=[],
                album_title=None,
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.assertEqual(
            self.service.list_album_group_track_ids(album_track_a),
            [album_track_a, album_track_b],
        )
        self.assertEqual(self.service.list_album_group_track_ids(single_track), [])
        self.assertEqual(self.service.list_album_group_track_ids(blank_album_track), [])

    def test_apply_album_metadata_to_tracks_updates_only_shared_album_fields(self):
        source_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00020",
                track_title="Source Track",
                artist_name="Album Artist",
                additional_artists=["Guest One"],
                album_title="Original Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc="T-123.456.789-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-77",
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00021",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=["Guest Two"],
                album_title="Original Album",
                release_date="2026-03-13",
                track_length_sec=321,
                iswc="T-123.456.780-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-88",
            )
        )

        updated_ids = self.service.apply_album_metadata_to_tracks(
            [peer_track],
            field_updates={
                "artist_name": "Renamed Album Artist",
                "album_title": "Renamed Album",
                "release_date": "2026-04-01",
                "upc": "999999999999",
                "genre": "Ambient",
                "catalog_number": "CAT-002",
            },
        )

        self.assertEqual(updated_ids, [peer_track])
        source_snapshot = self.service.fetch_track_snapshot(source_track)
        peer_snapshot = self.service.fetch_track_snapshot(peer_track)

        self.assertEqual(source_snapshot.artist_name, "Album Artist")
        self.assertEqual(source_snapshot.album_title, "Original Album")
        self.assertEqual(peer_snapshot.artist_name, "Renamed Album Artist")
        self.assertEqual(peer_snapshot.album_title, "Renamed Album")
        self.assertEqual(peer_snapshot.release_date, "2026-04-01")
        self.assertEqual(peer_snapshot.upc, "999999999999")
        self.assertEqual(peer_snapshot.genre, "Ambient")
        self.assertEqual(peer_snapshot.catalog_number, "CAT-002")
        self.assertEqual(peer_snapshot.track_title, "Peer Track")
        self.assertEqual(peer_snapshot.additional_artists, ["Guest Two"])
        self.assertEqual(peer_snapshot.track_length_sec, 321)
        self.assertEqual(peer_snapshot.iswc, "T-123.456.780-0")
        self.assertEqual(peer_snapshot.buma_work_number, "BUMA-88")

    def test_delete_track_removes_track_and_join_rows(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00003",
                track_title="Disposable Song",
                artist_name="Main Artist",
                additional_artists=["Guest One"],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.service.delete_track(track_id)

        self.assertIsNone(self.conn.execute("SELECT id FROM Tracks WHERE id=?", (track_id,)).fetchone())
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM TrackArtists WHERE track_id=?", (track_id,)).fetchone()
        )


if __name__ == "__main__":
    unittest.main()

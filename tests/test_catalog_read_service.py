import sqlite3
import unittest

from isrc_manager.services import CatalogReadService


def make_catalog_read_conn():
    conn = sqlite3.connect(":memory:")
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
            db_entry_date TEXT,
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
            release_date TEXT,
            track_length_sec INTEGER NOT NULL DEFAULT 0,
            iswc TEXT,
            upc TEXT,
            genre TEXT
        );
        CREATE TABLE TrackArtists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'additional'
        );
        CREATE TABLE CustomFieldValues (
            track_id INTEGER NOT NULL,
            field_def_id INTEGER NOT NULL,
            value TEXT,
            PRIMARY KEY (track_id, field_def_id)
        );
        """
    )
    conn.executemany(
        "INSERT INTO Artists(id, name) VALUES (?, ?)",
        [(1, "Main Artist"), (2, "Guest Artist"), (3, "Another Artist")],
    )
    conn.executemany(
        "INSERT INTO Albums(id, title) VALUES (?, ?)",
        [(1, "Album One"), (2, "Album Two")],
    )
    conn.executemany(
        """
        INSERT INTO Tracks(
            id, isrc, db_entry_date,
            audio_file_path, audio_file_mime_type, audio_file_size_bytes,
            track_title, catalog_number,
            album_art_path, album_art_mime_type, album_art_size_bytes,
            main_artist_id, buma_work_number, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "NL-ABC-26-00001",
                "2026-03-13",
                "track_media/audio/demo.wav",
                "audio/wav",
                512,
                "First Song",
                "CAT-001",
                "track_media/images/cover.png",
                "image/png",
                42,
                1,
                "BUMA-101",
                1,
                "2026-03-14",
                195,
                "T-123.456.789-0",
                "123456789012",
                "Pop",
            ),
            (
                2,
                "NL-ABC-26-00002",
                "2026-03-14",
                None,
                None,
                0,
                "Second Song",
                "",
                None,
                None,
                0,
                3,
                "",
                2,
                "2026-03-15",
                60,
                "",
                "",
                "Rock",
            ),
        ],
    )
    conn.execute("INSERT INTO TrackArtists(track_id, artist_id, role) VALUES (1, 2, 'additional')")
    conn.executemany(
        "INSERT INTO CustomFieldValues(track_id, field_def_id, value) VALUES (?, ?, ?)",
        [(1, 10, "Calm"), (2, 11, "Loud")],
    )
    conn.commit()
    return conn


class CatalogReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_catalog_read_conn()
        self.service = CatalogReadService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_fetch_rows_with_customs_returns_joined_catalog_data(self):
        rows, custom_map = self.service.fetch_rows_with_customs(
            [
                {"id": 10, "name": "Mood"},
                {"id": 11, "name": "Energy"},
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0],
            (
                1,
                "",
                "First Song",
                195,
                "Album One",
                "",
                "Main Artist",
                "Guest Artist",
                "NL-ABC-26-00001",
                "BUMA-101",
                "T-123.456.789-0",
                "123456789012",
                "CAT-001",
                "2026-03-13",
                "2026-03-14",
                "Pop",
            ),
        )
        self.assertEqual(custom_map[(1, 10)], "Calm")
        self.assertEqual(custom_map[(2, 11)], "Loud")

    def test_find_album_metadata_returns_first_track_values(self):
        self.assertEqual(
            self.service.find_album_metadata("Album One"),
            ("2026-03-14", "123456789012", "Pop"),
        )
        self.assertIsNone(self.service.find_album_metadata("Missing Album"))

    def test_catalog_reads_prefer_current_tracks_and_albums_tables(self):
        self.conn.executescript(
            """
            CREATE TABLE Tracks_legacy (
                id INTEGER PRIMARY KEY,
                album_id INTEGER,
                track_title TEXT,
                release_date TEXT,
                upc TEXT,
                genre TEXT
            );
            CREATE TABLE Albums_legacy (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            "INSERT INTO Albums_legacy(id, title) VALUES (?, ?)",
            (1, "Album One"),
        )
        self.conn.execute(
            """
            INSERT INTO Tracks_legacy(id, album_id, track_title, release_date, upc, genre)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, 1, "Legacy Song", "1999-12-31", "000000000000", "Legacy"),
        )

        rows, _ = self.service.fetch_rows_with_customs([])

        self.assertEqual(rows[0][2], "First Song")
        self.assertEqual(rows[0][4], "Album One")
        self.assertEqual(
            self.service.find_album_metadata("Album One"),
            ("2026-03-14", "123456789012", "Pop"),
        )

    def test_list_tracks_returns_title_sorted_choices(self):
        self.assertEqual(
            self.service.list_tracks(),
            [(1, "First Song"), (2, "Second Song")],
        )


if __name__ == "__main__":
    unittest.main()

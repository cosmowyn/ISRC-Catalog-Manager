import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService


class DatabaseSchemaMigrations3839Tests(unittest.TestCase):
    def test_migrate_38_to_39_backfills_party_artist_authority(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                service = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                service.init_db()

                conn.execute("DROP TABLE IF EXISTS TrackArtists")
                conn.execute("DROP TABLE IF EXISTS Tracks")
                conn.execute("DROP TABLE IF EXISTS Artists")
                conn.execute(
                    """
                    CREATE TABLE Artists (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        db_entry_date DATE,
                        track_title TEXT NOT NULL,
                        main_artist_id INTEGER NOT NULL,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE TrackArtists (
                        track_id INTEGER NOT NULL,
                        artist_id INTEGER NOT NULL,
                        role TEXT NOT NULL DEFAULT 'additional',
                        PRIMARY KEY (track_id, artist_id, role)
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO Artists(id, name) VALUES (?, ?)",
                    [
                        (1, "Legacy Main"),
                        (2, "Legacy Guest"),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(
                        id, isrc, isrc_compact, db_entry_date, track_title, main_artist_id, release_date, track_length_sec
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "NL-TST-26-39001",
                        "NLTST2639001",
                        "2026-04-09",
                        "Migrated Track",
                        1,
                        "2026-04-09",
                        201,
                    ),
                )
                conn.execute(
                    "INSERT INTO TrackArtists(track_id, artist_id, role) VALUES (1, 2, 'additional')"
                )
                conn.execute("PRAGMA user_version = 38")
                conn.commit()

                service.migrate_schema()

                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
                self.assertIsNone(
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='Artists'"
                    ).fetchone()
                )

                track_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()
                }
                track_artist_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(TrackArtists)").fetchall()
                }
                self.assertIn("main_artist_party_id", track_columns)
                self.assertNotIn("main_artist_id", track_columns)
                self.assertIn("party_id", track_artist_columns)
                self.assertNotIn("artist_id", track_artist_columns)

                main_row = conn.execute(
                    """
                    SELECT t.track_title, p.artist_name, p.party_type
                    FROM Tracks t
                    JOIN Parties p ON p.id = t.main_artist_party_id
                    WHERE t.id = 1
                    """
                ).fetchone()
                additional_rows = conn.execute(
                    """
                    SELECT p.artist_name
                    FROM TrackArtists ta
                    JOIN Parties p ON p.id = ta.party_id
                    WHERE ta.track_id = 1
                    ORDER BY p.artist_name
                    """
                ).fetchall()

                self.assertEqual(main_row, ("Migrated Track", "Legacy Main", "artist"))
                self.assertEqual(additional_rows, [("Legacy Guest",)])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

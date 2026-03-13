import sqlite3
import unittest

from isrc_manager.services import CatalogAdminService


def make_catalog_conn():
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
            track_title TEXT NOT NULL,
            main_artist_id INTEGER,
            album_id INTEGER
        );
        CREATE TABLE TrackArtists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'additional'
        );
        CREATE TABLE Licensees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE Licenses (
            id INTEGER PRIMARY KEY,
            track_id INTEGER NOT NULL,
            licensee_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            filename TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO Artists(id, name) VALUES (?, ?)",
        [
            (1, "Main Artist"),
            (2, "Featured Artist"),
            (3, "Unused Artist"),
        ],
    )
    conn.executemany(
        "INSERT INTO Albums(id, title) VALUES (?, ?)",
        [
            (1, "Used Album"),
            (2, "Unused Album"),
        ],
    )
    conn.execute(
        "INSERT INTO Tracks(id, track_title, main_artist_id, album_id) VALUES (1, 'Song A', 1, 1)"
    )
    conn.execute(
        "INSERT INTO TrackArtists(track_id, artist_id, role) VALUES (1, 2, 'additional')"
    )
    conn.executemany(
        "INSERT INTO Licensees(id, name) VALUES (?, ?)",
        [
            (1, "Busy Licensee"),
            (2, "Free Licensee"),
        ],
    )
    conn.execute(
        "INSERT INTO Licenses(id, track_id, licensee_id, file_path, filename) VALUES (1, 1, 1, 'licenses/a.pdf', 'a.pdf')"
    )
    conn.commit()
    return conn


class CatalogAdminServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_catalog_conn()
        self.service = CatalogAdminService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_lists_artist_and_album_usage_counts(self):
        artists = {artist.name: artist for artist in self.service.list_artists_with_usage()}
        albums = {album.title: album for album in self.service.list_albums_with_usage()}

        self.assertEqual((artists["Main Artist"].main_uses, artists["Main Artist"].extra_uses), (1, 0))
        self.assertEqual((artists["Featured Artist"].main_uses, artists["Featured Artist"].extra_uses), (0, 1))
        self.assertEqual(artists["Unused Artist"].total_uses, 0)
        self.assertEqual(albums["Used Album"].uses, 1)
        self.assertEqual(albums["Unused Album"].uses, 0)

    def test_delete_unused_artists_and_albums(self):
        self.service.delete_artists([3])
        self.service.delete_albums([2])

        self.assertIsNone(self.conn.execute("SELECT id FROM Artists WHERE id=3").fetchone())
        self.assertIsNone(self.conn.execute("SELECT id FROM Albums WHERE id=2").fetchone())

    def test_licensee_management_preserves_usage_rules(self):
        created_id = self.service.ensure_licensee("New Licensee")
        same_id = self.service.ensure_licensee("New Licensee")

        self.assertEqual(created_id, same_id)

        self.service.rename_licensee(created_id, "Renamed Licensee")
        self.assertEqual(
            self.conn.execute("SELECT name FROM Licensees WHERE id=?", (created_id,)).fetchone(),
            ("Renamed Licensee",),
        )

        with self.assertRaises(ValueError):
            self.service.delete_licensee(1)

        self.service.delete_licensee(2)
        self.assertIsNone(self.conn.execute("SELECT id FROM Licensees WHERE id=2").fetchone())


if __name__ == "__main__":
    unittest.main()

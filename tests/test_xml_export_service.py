import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from isrc_manager.services import XMLExportService


def make_export_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE Artists (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE Albums (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            album_art_path TEXT,
            album_art_mime_type TEXT,
            album_art_size_bytes INTEGER NOT NULL DEFAULT 0
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
        CREATE TABLE CustomFieldDefs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER,
            field_type TEXT NOT NULL DEFAULT 'text',
            options TEXT
        );
        CREATE TABLE CustomFieldValues (
            track_id INTEGER NOT NULL,
            field_def_id INTEGER NOT NULL,
            value TEXT,
            mime_type TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (track_id, field_def_id)
        );
        """
    )
    conn.executemany(
        "INSERT INTO Artists(id, name) VALUES (?, ?)",
        [(1, "Main Artist"), (2, "Guest Artist"), (3, "Second Artist")],
    )
    conn.execute(
        """
        INSERT INTO Albums(id, title, album_art_path, album_art_mime_type, album_art_size_bytes)
        VALUES (1, 'Album One', 'track_media/images/cover.png', 'image/png', 42)
        """
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
            (1, "NL-ABC-26-00001", "2026-03-13", "track_media/audio/demo.wav", "audio/wav", 512, "First Song", "CAT-001", None, None, 0, 1, "BUMA-42", 1, "2026-03-14", 195, "T-123.456.789-0", "123456789012", "Pop"),
            (2, "NL-ABC-26-00002", "2026-03-15", None, None, 0, "Second Song", "", None, None, 0, 3, "", None, "", 60, "", "", "Rock"),
        ],
    )
    conn.execute("INSERT INTO TrackArtists(track_id, artist_id, role) VALUES (1, 2, 'additional')")
    conn.executemany(
        """
        INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
        VALUES (?, ?, 1, ?, ?, ?)
        """,
        [
            (1, "Mood", 0, "dropdown", '["Calm"]'),
            (2, "Artwork", 1, "blob_image", None),
        ],
    )
    conn.executemany(
        """
        INSERT INTO CustomFieldValues(track_id, field_def_id, value, mime_type, size_bytes)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "Calm", None, 0),
            (1, 2, None, "image/png", 42),
        ],
    )
    conn.commit()
    return conn


class XMLExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_export_conn()
        self.service = XMLExportService(self.conn)
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_export_all_writes_full_schema_xml(self):
        output = Path(self.tmpdir.name) / "full.xml"

        exported = self.service.export_all(output)
        tree = ET.parse(output)
        root = tree.getroot()

        self.assertEqual(exported, 2)
        self.assertEqual(root.tag, "DeclarationOfSoundRecordingRightsClaimMessage")
        recordings = root.findall("SoundRecording")
        self.assertEqual(len(recordings), 2)
        first = recordings[0]
        self.assertEqual(first.findtext("track_title"), "First Song")
        self.assertEqual(first.findtext("TrackLength"), "00:03:15")
        self.assertEqual(first.findtext("track_length_sec"), "195")
        self.assertEqual(first.findtext("catalog_number"), "CAT-001")
        self.assertEqual(first.findtext("buma_work_number"), "BUMA-42")
        self.assertEqual(first.findtext("audio_file_mime_type"), "audio/wav")
        self.assertEqual(first.findtext("album_art_size_bytes"), "42")
        mood = first.find("./CustomFields/Field[@name='Mood']/Value")
        artwork_size = first.find("./CustomFields/Field[@name='Artwork']/SizeBytes")
        self.assertIsNotNone(mood)
        self.assertEqual(mood.text, "Calm")
        self.assertIsNotNone(artwork_size)
        self.assertEqual(artwork_size.text, "42")

    def test_export_selected_writes_selected_schema_xml(self):
        output = Path(self.tmpdir.name) / "selected.xml"

        exported = self.service.export_selected(output, [1], current_db_path="/tmp/profile.db")
        tree = ET.parse(output)
        root = tree.getroot()

        self.assertEqual(exported, 1)
        self.assertEqual(root.tag, "ISRCExport")
        self.assertEqual(root.findtext("./Meta/ProfileDB"), "/tmp/profile.db")
        tracks = root.findall("./Tracks/Track")
        self.assertEqual(len(tracks), 1)
        track = tracks[0]
        self.assertEqual(track.attrib["id"], "1")
        self.assertEqual(track.findtext("ISRC"), "NL-ABC-26-00001")
        self.assertEqual(track.findtext("Title"), "First Song")
        self.assertEqual(track.findtext("AdditionalArtists"), "Guest Artist")
        self.assertEqual(track.findtext("TrackLength"), "00:03:15")
        self.assertEqual(track.findtext("CatalogNumber"), "CAT-001")
        self.assertEqual(track.findtext("BUMAWorkNumber"), "BUMA-42")
        self.assertEqual(track.findtext("AudioFileMimeType"), "audio/wav")
        self.assertEqual(track.findtext("AlbumArtSizeBytes"), "42")
        self.assertEqual(track.findtext("./CustomFields/Field[@name='Mood']/Value"), "Calm")
        self.assertEqual(track.findtext("./CustomFields/Field[@name='Artwork']/MimeType"), "image/png")


if __name__ == "__main__":
    unittest.main()

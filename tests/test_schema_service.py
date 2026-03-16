import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService


class DatabaseSchemaServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.service = DatabaseSchemaService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_init_db_and_migrate_schema_reach_current_target(self):
        self.service.init_db()
        self.service.migrate_schema()

        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        value_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
        }
        album_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(Albums)").fetchall()
        }
        track_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(Tracks)").fetchall()
        }
        gs1_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(GS1Metadata)").fetchall()
        }
        track_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(Tracks)").fetchall()
        }
        gs1_indexes = {
            row[1] for row in self.conn.execute("PRAGMA index_list(GS1Metadata)").fetchall()
        }
        triggers = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }

        self.assertEqual(self.service.get_db_version(), SCHEMA_TARGET)
        self.assertIn("HistoryEntries", tables)
        self.assertIn("HistorySnapshots", tables)
        self.assertIn("HistoryHead", tables)
        self.assertIn("Licensees", tables)
        self.assertIn("GS1Metadata", tables)
        self.assertIn("GS1TemplateStorage", tables)
        self.assertIn("Releases", tables)
        self.assertIn("ReleaseTracks", tables)
        self.assertIn("vw_Licenses", tables)
        self.assertIn("contract_number", gs1_columns)
        self.assertTrue({"blob_value", "mime_type", "size_bytes"} <= value_columns)
        self.assertTrue(
            {
                "album_art_path",
                "album_art_mime_type",
                "album_art_size_bytes",
            }
            <= album_columns
        )
        self.assertTrue(
            {
                "audio_file_path",
                "audio_file_mime_type",
                "audio_file_size_bytes",
                "catalog_number",
                "album_art_path",
                "album_art_mime_type",
                "album_art_size_bytes",
                "buma_work_number",
                "composer",
                "publisher",
                "comments",
                "lyrics",
            }
            <= track_columns
        )
        self.assertIn("idx_tracks_isrc_compact_unique", track_indexes)
        self.assertIn("idx_tracks_catalog_number", track_indexes)
        self.assertIn("idx_tracks_buma_work_number", track_indexes)
        self.assertIn("idx_gs1_metadata_export_enabled", gs1_indexes)
        self.assertIn("idx_gs1_metadata_contract_number", gs1_indexes)
        self.assertIn("trg_auditlog_no_update", triggers)

    def test_migrate_12_to_13_promotes_default_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        track_title TEXT NOT NULL,
                        main_artist_id INTEGER NOT NULL,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0,
                        iswc TEXT,
                        upc TEXT,
                        genre TEXT
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
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                    VALUES (1, 'NL-ABC-26-00001', 'NLABC2600001', 'Migrated Song', 1, NULL, '2026-03-13', 180, NULL, NULL, NULL)
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Catalog#", 1, "text"),
                        (2, "BUMA Wnr.", 2, "text"),
                        (3, "Audio File", 3, "blob_audio"),
                        (4, "Album Art", 4, "blob_image"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "CAT-LEGACY-01", None, None, 0),
                        (1, 2, "BUMA-LEGACY-99", None, None, 0),
                        (1, 3, None, sqlite3.Binary(b"WAVE"), "audio/wav", 4),
                        (1, 4, None, sqlite3.Binary(b"PNG!"), "image/png", 4),
                    ],
                )
                conn.execute("PRAGMA user_version = 12")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        catalog_number,
                        buma_work_number,
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        album_art_path,
                        album_art_mime_type,
                        album_art_size_bytes
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "CAT-LEGACY-01")
                self.assertEqual(row[1], "BUMA-LEGACY-99")
                self.assertTrue(str(row[2]).startswith("track_media/audio/"))
                self.assertEqual(row[3], "audio/wav")
                self.assertEqual(row[4], 4)
                self.assertTrue(str(row[5]).startswith("track_media/images/"))
                self.assertEqual(row[6], "image/png")
                self.assertEqual(row[7], 4)

                audio_path = Path(tmpdir) / str(row[2])
                art_path = Path(tmpdir) / str(row[5])
                self.assertEqual(audio_path.read_bytes(), b"WAVE")
                self.assertEqual(art_path.read_bytes(), b"PNG!")
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
                    0,
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def test_current_schema_allows_multiple_blank_isrc_rows(self):
        self.service.init_db()
        self.service.migrate_schema()

        self.conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Schema Artist')")
        self.conn.execute(
            """
            INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, track_length_sec)
            VALUES ('', '', 'Blank ISRC One', 1, 0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, track_length_sec)
            VALUES ('', '', 'Blank ISRC Two', 1, 0)
            """
        )

        rows = self.conn.execute("SELECT isrc, isrc_compact FROM Tracks ORDER BY id").fetchall()
        self.assertEqual(rows, [("", ""), ("", "")])

    def test_migrate_13_to_14_reconciles_leftover_promoted_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        db_entry_date DATE,
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
                        genre TEXT
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
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(
                        id, isrc, isrc_compact, db_entry_date,
                        audio_file_path, audio_file_mime_type, audio_file_size_bytes,
                        track_title, catalog_number,
                        album_art_path, album_art_mime_type, album_art_size_bytes,
                        main_artist_id, buma_work_number, album_id, release_date, track_length_sec, iswc, upc, genre
                    )
                    VALUES (
                        1, 'NL-ABC-26-00001', 'NLABC2600001', '2026-03-13',
                        NULL, NULL, 0,
                        'Migrated Again', NULL,
                        NULL, NULL, 0,
                        1, NULL, NULL, '2026-03-13', 180, NULL, NULL, NULL
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Catalog#", 1, "text"),
                        (2, "BUMA Wnr.", 2, "text"),
                        (3, "Audio File", 3, "blob_audio"),
                        (4, "Album Art", 4, "blob_image"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "CAT-V13-01", None, None, 0),
                        (1, 2, "BUMA-V13-88", None, None, 0),
                        (1, 3, None, sqlite3.Binary(b"AUDI"), "audio/wav", 4),
                        (1, 4, None, sqlite3.Binary(b"IMAG"), "image/png", 4),
                    ],
                )
                conn.execute("PRAGMA user_version = 13")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        catalog_number,
                        buma_work_number,
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        album_art_path,
                        album_art_mime_type,
                        album_art_size_bytes
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertEqual(row[0], "CAT-V13-01")
                self.assertEqual(row[1], "BUMA-V13-88")
                self.assertTrue(str(row[2]).startswith("track_media/audio/"))
                self.assertEqual(row[3], "audio/wav")
                self.assertEqual(row[4], 4)
                self.assertTrue(str(row[5]).startswith("track_media/images/"))
                self.assertEqual(row[6], "image/png")
                self.assertEqual(row[7], 4)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
                    0,
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def test_migration_skips_same_name_fields_with_different_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(
                    """
                    CREATE TABLE Tracks (
                        id INTEGER PRIMARY KEY,
                        isrc TEXT NOT NULL,
                        isrc_compact TEXT,
                        track_title TEXT NOT NULL,
                        main_artist_id INTEGER NOT NULL,
                        album_id INTEGER,
                        release_date DATE,
                        track_length_sec INTEGER NOT NULL DEFAULT 0,
                        iswc TEXT,
                        upc TEXT,
                        genre TEXT
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
                        blob_value BLOB,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (track_id, field_def_id)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO Tracks(id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                    VALUES (1, 'NL-ABC-26-00001', 'NLABC2600001', 'Keep Custom Types', 1, NULL, '2026-03-13', 180, NULL, NULL, NULL)
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
                    VALUES (?, ?, 1, ?, ?, NULL)
                    """,
                    [
                        (1, "Audio File", 1, "text"),
                        (2, "Catalog#", 2, "dropdown"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO CustomFieldValues(track_id, field_def_id, value, blob_value, mime_type, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 1, "not-a-blob", None, None, 0),
                        (1, 2, "CAT-OPTION", None, None, 0),
                    ],
                )
                conn.execute("PRAGMA user_version = 12")
                conn.commit()

                service = DatabaseSchemaService(conn, data_root=tmpdir)
                service.migrate_schema()

                row = conn.execute(
                    """
                    SELECT
                        audio_file_path,
                        audio_file_mime_type,
                        audio_file_size_bytes,
                        catalog_number
                    FROM Tracks
                    WHERE id = 1
                    """
                ).fetchone()
                self.assertEqual(row, (None, None, 0, None))
                self.assertEqual(
                    conn.execute(
                        "SELECT name, field_type FROM CustomFieldDefs ORDER BY id"
                    ).fetchall(),
                    [("Audio File", "text"), ("Catalog#", "dropdown")],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT track_id, field_def_id, value FROM CustomFieldValues ORDER BY field_def_id"
                    ).fetchall(),
                    [(1, 1, "not-a-blob"), (1, 2, "CAT-OPTION")],
                )
                self.assertEqual(service.get_db_version(), SCHEMA_TARGET)
            finally:
                conn.close()

    def test_init_db_tolerates_older_tracks_schema_before_migration(self):
        conn = sqlite3.connect(":memory:")
        try:
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
                    isrc_compact TEXT,
                    track_title TEXT NOT NULL,
                    main_artist_id INTEGER NOT NULL,
                    album_id INTEGER,
                    release_date DATE,
                    track_length_sec INTEGER NOT NULL DEFAULT 0,
                    iswc TEXT,
                    upc TEXT,
                    genre TEXT
                );
                """
            )
            service = DatabaseSchemaService(conn)

            service.init_db()

            track_columns = {row[1] for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()}
            track_indexes = {row[1] for row in conn.execute("PRAGMA index_list(Tracks)").fetchall()}
            self.assertTrue(
                {
                    "db_entry_date",
                    "isrc_compact",
                    "track_length_sec",
                    "audio_file_path",
                    "audio_file_mime_type",
                    "audio_file_size_bytes",
                    "catalog_number",
                    "album_art_path",
                    "album_art_mime_type",
                    "album_art_size_bytes",
                    "buma_work_number",
                }
                <= track_columns
            )
            self.assertIn("idx_tracks_isrc_unique", track_indexes)
            self.assertIn("idx_tracks_isrc_compact_unique", track_indexes)
            self.assertIn("idx_tracks_title", track_indexes)
            self.assertIn("idx_tracks_upc", track_indexes)
            self.assertIn("idx_tracks_genre", track_indexes)
            self.assertIn("idx_tracks_catalog_number", track_indexes)
            self.assertIn("idx_tracks_buma_work_number", track_indexes)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

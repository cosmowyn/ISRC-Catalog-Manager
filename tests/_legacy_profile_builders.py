import sqlite3
from pathlib import Path


def build_legacy_v12_profile(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE app_kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

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
        conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Legacy Artist')")
        conn.execute("INSERT INTO Albums(id, title) VALUES (1, 'Legacy Album')")
        conn.execute(
            """
            INSERT INTO Tracks(
                id,
                isrc,
                isrc_compact,
                track_title,
                main_artist_id,
                album_id,
                release_date,
                track_length_sec,
                iswc,
                upc,
                genre
            )
            VALUES (
                1,
                'NL-ABC-26-00001',
                'NLABC2600001',
                'Legacy Orbit',
                1,
                1,
                '2026-03-13',
                180,
                'T-111.222.333-4',
                '036000291452',
                'Ambient'
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
                (1, 1, "CAT-LEGACY-01", None, None, 0),
                (1, 2, "BUMA-LEGACY-99", None, None, 0),
                (1, 3, None, sqlite3.Binary(b"WAVE"), "audio/wav", 4),
                (1, 4, None, sqlite3.Binary(b"PNG!"), "image/png", 4),
            ],
        )
        conn.execute("PRAGMA user_version = 12")
        conn.commit()
    finally:
        conn.close()

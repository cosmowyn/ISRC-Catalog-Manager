import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path

from isrc_manager.services import CustomFieldDefinitionService, TrackService, XMLImportService


def make_import_conn():
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
            genre TEXT
        );
        CREATE TABLE TrackArtists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'additional',
            PRIMARY KEY (track_id, artist_id, role)
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
            PRIMARY KEY (track_id, field_def_id)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO CustomFieldDefs(id, name, active, sort_order, field_type, options)
        VALUES (1, 'Mood', 1, 0, 'dropdown', '["Happy","Calm"]')
        """
    )
    conn.execute("INSERT INTO Artists(id, name) VALUES (1, 'Existing Artist')")
    conn.execute(
        """
        INSERT INTO Tracks(
            id, isrc, isrc_compact,
            audio_file_path, audio_file_mime_type, audio_file_size_bytes,
            track_title, catalog_number,
            album_art_path, album_art_mime_type, album_art_size_bytes,
            main_artist_id, buma_work_number, album_id, release_date, track_length_sec, iswc, upc, genre
        )
        VALUES (
            1, 'NL-ABC-26-00001', 'NLABC2600001',
            NULL, NULL, 0,
            'Existing Song', NULL,
            NULL, NULL, 0,
            1, NULL, NULL, '2026-03-13', 180, NULL, NULL, NULL
        )
        """
    )
    conn.commit()
    return conn


class XMLImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_import_conn()
        self.track_service = TrackService(self.conn)
        self.custom_fields = CustomFieldDefinitionService(self.conn)
        self.service = XMLImportService(self.conn, self.track_service, self.custom_fields)
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _write_xml(self, name: str, contents: str) -> str:
        path = Path(self.tmpdir.name) / name
        path.write_text(textwrap.dedent(contents).strip(), encoding="utf-8")
        return str(path)

    def test_inspect_selected_export_counts_duplicates_and_invalid_rows(self):
        file_path = self._write_xml(
            "selected.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00001</ISRC>
                  <Title>Duplicate Song</Title>
                  <MainArtist>Existing Artist</MainArtist>
                  <TrackLength>00:03:00</TrackLength>
                </Track>
                <Track>
                  <ISRC>bad</ISRC>
                  <Title>Broken Song</Title>
                  <MainArtist>Someone</MainArtist>
                  <TrackLength>00:03:00</TrackLength>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        inspection = self.service.inspect_file(file_path)

        self.assertEqual(inspection.schema, "selected")
        self.assertEqual(inspection.duplicate_count, 1)
        self.assertEqual(inspection.invalid_count, 1)
        self.assertEqual(inspection.would_insert, 0)
        self.assertEqual(len(inspection.records), 1)

    def test_inspect_reports_missing_custom_field_definitions(self):
        file_path = self._write_xml(
            "missing-fields.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00002</ISRC>
                  <Title>New Song</Title>
                  <MainArtist>New Artist</MainArtist>
                  <TrackLength>00:03:15</TrackLength>
                  <CustomFields>
                    <Field name="Energy" type="text">
                      <Value>High</Value>
                    </Field>
                  </CustomFields>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        inspection = self.service.inspect_file(file_path)

        self.assertEqual(inspection.missing_custom_fields, [("Energy", "text")])
        self.assertEqual(inspection.conflicting_custom_fields, [])

    def test_inspect_reports_conflicting_custom_field_types(self):
        file_path = self._write_xml(
            "conflicting-fields.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00002</ISRC>
                  <Title>New Song</Title>
                  <MainArtist>New Artist</MainArtist>
                  <TrackLength>00:03:15</TrackLength>
                  <CustomFields>
                    <Field name="Mood" type="text">
                      <Value>High</Value>
                    </Field>
                  </CustomFields>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        inspection = self.service.inspect_file(file_path)

        self.assertEqual(inspection.missing_custom_fields, [])
        self.assertEqual(inspection.conflicting_custom_fields, [("Mood", "text", "dropdown")])

    def test_execute_import_inserts_tracks_artists_and_custom_values(self):
        file_path = self._write_xml(
            "import.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00002</ISRC>
                  <Title>New Song</Title>
                  <MainArtist>New Artist</MainArtist>
                  <AdditionalArtists>Guest One, Guest Two</AdditionalArtists>
                  <Album>Fresh Album</Album>
                  <ReleaseDate>2026-03-14</ReleaseDate>
                  <TrackLength>00:03:15</TrackLength>
                  <ISWC>T-123.456.789-0</ISWC>
                  <UPCEAN>123456789012</UPCEAN>
                  <CatalogNumber>CAT-IMP-001</CatalogNumber>
                  <BUMAWorkNumber>BUMA-IMP-55</BUMAWorkNumber>
                  <Genre>Pop</Genre>
                  <CustomFields>
                    <Field name="Mood" type="dropdown">
                      <Value>Calm</Value>
                    </Field>
                  </CustomFields>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        result = self.service.execute_import(file_path)

        self.assertEqual((result.inserted, result.duplicate_count, result.invalid_count, result.error_count), (1, 0, 0, 0))
        row = self.conn.execute(
            """
            SELECT
                t.isrc,
                t.track_title,
                a.name,
                al.title,
                t.release_date,
                t.track_length_sec,
                t.iswc,
                t.upc,
                t.genre,
                t.catalog_number,
                t.buma_work_number
            FROM Tracks t
            JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.isrc_compact='NLABC2600002'
            """
        ).fetchone()
        extras = self.conn.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id = (SELECT id FROM Tracks WHERE isrc_compact='NLABC2600002')
            ORDER BY a.name
            """
        ).fetchall()
        custom = self.conn.execute(
            """
            SELECT value
            FROM CustomFieldValues
            WHERE track_id = (SELECT id FROM Tracks WHERE isrc_compact='NLABC2600002')
              AND field_def_id = 1
            """
        ).fetchone()

        self.assertEqual(
            row,
            (
                "NL-ABC-26-00002",
                "New Song",
                "New Artist",
                "Fresh Album",
                "2026-03-14",
                195,
                "T-123.456.789-0",
                "123456789012",
                "Pop",
                "CAT-IMP-001",
                "BUMA-IMP-55",
            ),
        )
        self.assertEqual([name for (name,) in extras], ["Guest One", "Guest Two"])
        self.assertEqual(custom, ("Calm",))

    def test_execute_import_can_create_missing_custom_fields(self):
        file_path = self._write_xml(
            "create-fields.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00003</ISRC>
                  <Title>Created Field Song</Title>
                  <MainArtist>New Artist</MainArtist>
                  <TrackLength>00:03:15</TrackLength>
                  <CustomFields>
                    <Field name="Energy" type="dropdown">
                      <Value>High</Value>
                    </Field>
                  </CustomFields>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        result = self.service.execute_import(file_path, create_missing_custom_fields=True)

        self.assertEqual((result.inserted, result.duplicate_count, result.invalid_count, result.error_count), (1, 0, 0, 0))
        field_row = self.conn.execute(
            "SELECT field_type, options FROM CustomFieldDefs WHERE name='Energy'"
        ).fetchone()
        custom_row = self.conn.execute(
            """
            SELECT cfv.value
            FROM CustomFieldValues cfv
            JOIN Tracks t ON t.id = cfv.track_id
            JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
            WHERE t.isrc_compact='NLABC2600003' AND cfd.name='Energy'
            """
        ).fetchone()

        self.assertEqual(field_row, ("dropdown", '["High"]'))
        self.assertEqual(custom_row, ("High",))


if __name__ == "__main__":
    unittest.main()

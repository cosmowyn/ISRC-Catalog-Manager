import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path

from isrc_manager.parties import PartyService
from isrc_manager.services import (
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
    XMLImportService,
)
from isrc_manager.works import WorkPayload, WorkService


def make_import_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    conn.commit()
    return conn


class XMLImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_import_conn()
        self.track_service = TrackService(self.conn)
        self.custom_fields = CustomFieldDefinitionService(self.conn)
        self.custom_fields.ensure_fields(
            [
                {
                    "name": "Mood",
                    "field_type": "dropdown",
                    "options": '["Happy","Calm"]',
                }
            ]
        )
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        existing_work_id = self.work_service.create_work(WorkPayload(title="Existing Song"))
        self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="Existing Song",
                artist_name="Existing Artist",
                additional_artists=[],
                album_title=None,
                release_date="2026-03-13",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
                work_id=existing_work_id,
            )
        )
        self.service = XMLImportService(
            self.conn,
            self.track_service,
            self.custom_fields,
            party_service=self.party_service,
            work_service=self.work_service,
            profile_name="import-test.db",
        )
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

        self.assertEqual(
            (result.inserted, result.duplicate_count, result.invalid_count, result.error_count),
            (1, 0, 0, 0),
        )
        row = self.conn.execute(
            """
            SELECT
                t.isrc,
                t.track_title,
                COALESCE(a.display_name, a.artist_name, a.legal_name),
                al.title,
                t.release_date,
                t.track_length_sec,
                t.iswc,
                t.upc,
                t.genre,
                t.catalog_number,
                t.buma_work_number,
                t.work_id,
                w.title
            FROM Tracks t
            JOIN Parties a ON a.id = t.main_artist_party_id
            LEFT JOIN Albums al ON al.id = t.album_id
            LEFT JOIN Works w ON w.id = t.work_id
            WHERE t.isrc_compact='NLABC2600002'
            """
        ).fetchone()
        extras = self.conn.execute(
            """
            SELECT COALESCE(a.display_name, a.artist_name, a.legal_name)
            FROM TrackArtists ta
            JOIN Parties a ON a.id = ta.party_id
            WHERE ta.track_id = (SELECT id FROM Tracks WHERE isrc_compact='NLABC2600002')
            ORDER BY COALESCE(a.display_name, a.artist_name, a.legal_name)
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
            row[:11],
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
        self.assertIsNotNone(row[11])
        self.assertEqual(row[12], "New Song")
        self.assertEqual([name for (name,) in extras], ["Guest One", "Guest Two"])
        self.assertEqual(custom, ("Calm",))

    def test_execute_import_allows_blank_isrc_rows(self):
        file_path = self._write_xml(
            "blank-isrc.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC></ISRC>
                  <Title>No Code Yet</Title>
                  <MainArtist>New Artist</MainArtist>
                  <Album>Indie Album</Album>
                  <TrackLength>00:03:15</TrackLength>
                </Track>
              </Tracks>
            </ISRCExport>
            """,
        )

        result = self.service.execute_import(file_path)

        self.assertEqual(
            (result.inserted, result.duplicate_count, result.invalid_count, result.error_count),
            (1, 0, 0, 0),
        )
        row = self.conn.execute(
            """
            SELECT isrc, isrc_compact, track_title, work_id
            FROM Tracks
            WHERE track_title = 'No Code Yet'
            """
        ).fetchone()
        self.assertEqual(row[:3], ("", "", "No Code Yet"))
        self.assertIsNotNone(row[3])

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

        self.assertEqual(
            (result.inserted, result.duplicate_count, result.invalid_count, result.error_count),
            (1, 0, 0, 0),
        )
        field_row = self.conn.execute(
            "SELECT field_type, options FROM CustomFieldDefs WHERE name='Energy'"
        ).fetchone()
        custom_row = self.conn.execute(
            """
            SELECT cfv.value, t.work_id
            FROM CustomFieldValues cfv
            JOIN Tracks t ON t.id = cfv.track_id
            JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
            WHERE t.isrc_compact='NLABC2600003' AND cfd.name='Energy'
            """
        ).fetchone()

        self.assertEqual(field_row, ("dropdown", '["High"]'))
        self.assertEqual(custom_row[0], "High")
        self.assertIsNotNone(custom_row[1])

    def test_execute_import_queues_blocked_rows_before_raising(self):
        file_path = self._write_xml(
            "queued-failure.xml",
            """
            <ISRCExport>
              <Tracks>
                <Track>
                  <ISRC>NL-ABC-26-00999</ISRC>
                  <Title>Queued XML Row</Title>
                  <MainArtist>Queued XML Artist</MainArtist>
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

        with self.assertRaisesRegex(ValueError, "Missing custom columns"):
            self.service.execute_import(file_path)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
        queued_rows = self.conn.execute(
            """
            SELECT status, source_format
            FROM TrackImportRepairQueue
            ORDER BY id
            """
        ).fetchall()
        self.assertEqual(queued_rows, [("pending", "xml")])


if __name__ == "__main__":
    unittest.main()

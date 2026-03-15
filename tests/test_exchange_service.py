import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from isrc_manager.exchange import ExchangeImportOptions, ExchangeService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import CustomFieldDefinitionService, CustomFieldValueService, DatabaseSchemaService, TrackCreatePayload, TrackService


class ExchangeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        DatabaseSchemaService(self.conn, data_root=self.data_root).init_db()
        DatabaseSchemaService(self.conn, data_root=self.data_root).migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.custom_defs = CustomFieldDefinitionService(self.conn)
        self.custom_values = CustomFieldValueService(self.conn, self.custom_defs)
        self.service = ExchangeService(
            self.conn,
            self.track_service,
            self.release_service,
            self.custom_defs,
            self.data_root,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(self, *, isrc: str, title: str, audio: bool = False) -> int:
        audio_path = None
        if audio:
            audio_path = self.data_root / f"{title}.wav"
            audio_path.write_bytes(b"RIFFdemo")
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Cosmowyn",
                additional_artists=["Guest"],
                album_title="Orbit Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc="T-123.456.789-0",
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-001",
                buma_work_number="BUMA-001",
                composer="Composer",
                publisher="Cosmowyn Records",
                comments="Comment",
                lyrics="Lyrics",
                audio_file_source_path=str(audio_path) if audio_path else None,
                album_art_source_path=None,
            )
        )

    def _create_release(self, track_id: int) -> int:
        return self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Cosmowyn",
                album_artist="Cosmowyn",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-001",
                upc="036000291452",
                territory="Worldwide",
                placements=[ReleaseTrackPlacement(track_id=track_id, disc_number=1, track_number=1, sequence_number=1)],
            )
        )

    def test_json_round_trip_preserves_release_and_custom_fields(self):
        track_id = self._create_track(isrc="NL-ABC-26-00001", title="Orbit")
        release_id = self._create_release(track_id)
        field = self.custom_defs.ensure_fields([{"name": "Mood", "field_type": "text"}])[0]
        self.custom_values.save_value(track_id, int(field["id"]), value="Dreamy")

        export_path = self.data_root / "catalog.json"
        self.service.export_json(export_path)

        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=self.data_root).init_db()
            DatabaseSchemaService(new_conn, data_root=self.data_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, self.data_root),
                ReleaseService(new_conn, self.data_root),
                CustomFieldDefinitionService(new_conn),
                self.data_root,
            )
            report = new_service.import_json(export_path, options=ExchangeImportOptions(mode="create"))

            self.assertEqual(report.failed, 0)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Releases").fetchone()[0], 1)
            self.assertEqual(
                new_conn.execute(
                    """
                    SELECT cfv.value
                    FROM CustomFieldValues cfv
                    JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
                    WHERE cfd.name='Mood'
                    """
                ).fetchone()[0],
                "Dreamy",
            )
            self.assertEqual(
                new_conn.execute("SELECT COUNT(*) FROM ReleaseTracks WHERE release_id=1").fetchone()[0],
                1,
            )
        finally:
            new_conn.close()

    def test_update_mode_skips_unmatched_rows(self):
        csv_path = self.data_root / "import.csv"
        csv_path.write_text(
            "track_title,artist_name,isrc\nUnmatched,Cosmowyn,NL-ABC-26-99999\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={"track_title": "track_title", "artist_name": "artist_name", "isrc": "isrc"},
            options=ExchangeImportOptions(mode="update"),
        )

        self.assertEqual(report.passed, 0)
        self.assertEqual(report.skipped, 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 0)

    def test_package_export_writes_manifest_and_media(self):
        track_id = self._create_track(isrc="NL-ABC-26-00002", title="Nebula", audio=True)
        self._create_release(track_id)

        package_path = self.data_root / "package.zip"
        row_count = self.service.export_package(package_path)
        self.assertGreaterEqual(row_count, 1)

        with ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertTrue(any(name.startswith("media/track_media/audio/") for name in names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertTrue(manifest["packaged_media"])

    def test_inspect_csv_suggests_known_headers(self):
        csv_path = self.data_root / "headers.csv"
        csv_path.write_text("track_title,artist_name,custom::Mood\nOrbit,Cosmowyn,Dreamy\n", encoding="utf-8")

        inspection = self.service.inspect_csv(csv_path)

        self.assertEqual(inspection.suggested_mapping["track_title"], "track_title")
        self.assertEqual(inspection.suggested_mapping["artist_name"], "artist_name")
        self.assertEqual(inspection.suggested_mapping["custom::Mood"], "custom::Mood")


if __name__ == "__main__":
    unittest.main()

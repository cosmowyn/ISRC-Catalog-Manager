import json
import sqlite3
import tempfile
import unittest
from datetime import time, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from isrc_manager.exchange import ExchangeImportOptions, ExchangeService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import (
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseSchemaService,
    LicenseService,
    TrackCreatePayload,
    TrackService,
)


class ExchangeServiceTestCase(unittest.TestCase):
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
                artist_name="Moonwake",
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
                publisher="Moonwake Records",
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
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-001",
                upc="036000291452",
                territory="Worldwide",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )

    def _fetch_release_row_for_track(self, track_id: int) -> tuple[str, str, str, str, str] | None:
        return self.conn.execute(
            """
            SELECT
                r.title,
                COALESCE(r.primary_artist, ''),
                COALESCE(r.album_artist, ''),
                COALESCE(r.catalog_number, ''),
                COALESCE(r.upc, '')
            FROM Releases r
            JOIN ReleaseTracks rt ON rt.release_id = r.id
            WHERE rt.track_id=?
            ORDER BY r.id
            LIMIT 1
            """,
            (track_id,),
        ).fetchone()

    def _fetch_custom_value(self, track_id: int, field_name: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT cfv.value
            FROM CustomFieldValues cfv
            JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
            WHERE cfv.track_id=? AND cfd.name=?
            """,
            (track_id, field_name),
        ).fetchone()
        return None if row is None else str(row[0] or "")

    def case_json_round_trip_preserves_release_and_custom_fields(self):
        track_id = self._create_track(isrc="NL-ABC-26-00001", title="Orbit")
        self._create_release(track_id)
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
            report = new_service.import_json(
                export_path, options=ExchangeImportOptions(mode="create")
            )

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
                new_conn.execute(
                    "SELECT COUNT(*) FROM ReleaseTracks WHERE release_id=1"
                ).fetchone()[0],
                1,
            )
        finally:
            new_conn.close()

    def case_update_mode_skips_unmatched_rows(self):
        csv_path = self.data_root / "import.csv"
        csv_path.write_text(
            "track_title,artist_name,isrc\nUnmatched,Moonwake,NL-ABC-26-99999\n",
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

    def case_import_csv_creates_track_from_multiple_columns(self):
        csv_path = self.data_root / "create-import.csv"
        csv_path.write_text(
            "track_title,artist_name,isrc,comments\n"
            "Orbit,Moonwake,NL-ABC-26-00031,Demo import\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "isrc": "isrc",
                "comments": "comments",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(len(report.created_tracks), 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT t.track_title, COALESCE(a.name, ''), t.isrc, t.comments
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                """
            ).fetchone(),
            ("Orbit", "Moonwake", "NL-ABC-26-00031", "Demo import"),
        )

    def case_import_csv_detects_semicolon_delimiter(self):
        csv_path = self.data_root / "semicolon-import.csv"
        csv_path.write_text(
            "track_title;artist_name;isrc;comments\n"
            "Orbit;Moonwake;NL-ABC-26-00032;Semicolon import\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "isrc": "isrc",
                "comments": "comments",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(len(report.created_tracks), 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT t.track_title, COALESCE(a.name, ''), t.isrc, t.comments
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.id=?
                """,
                (report.created_tracks[0],),
            ).fetchone(),
            ("Orbit", "Moonwake", "NL-ABC-26-00032", "Semicolon import"),
        )

    def case_package_export_writes_manifest_and_media(self):
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
        self.assertTrue(
            any(str(row.get("audio_file_path") or "").strip() for row in manifest["rows"])
        )
        self.assertTrue(isinstance(manifest.get("packaged_media_index"), dict))
        self.assertTrue(manifest["packaged_media_index"])

    def case_package_export_includes_legacy_license_files_column(self):
        track_id = self._create_track(isrc="NL-ABC-26-00033", title="License Trail")
        self._create_release(track_id)
        license_service = LicenseService(self.conn, self.data_root)
        license_pdf = self.data_root / "track-license.pdf"
        license_pdf.write_bytes(b"%PDF-1.4\nlicense export test\n")
        license_service.add_license(
            track_id=track_id,
            licensee_name="Moonwake Rights",
            source_pdf_path=license_pdf,
        )

        package_path = self.data_root / "license-package.zip"
        self.service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        self.assertIn("license_files", manifest["columns"])
        self.assertEqual(manifest["rows"][0]["license_files"], "track-license.pdf")

    def case_package_export_includes_shared_album_art_once(self):
        artwork_path = self.data_root / "cover.png"
        artwork_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A"
                "0000000D49484452000000010000000108060000001F15C489"
                "0000000D49444154789C63F8FFFF3F0005FE02FEA7D6059F"
                "0000000049454E44AE426082"
            )
        )
        track_a = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00021",
                track_title="Remix A",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Shared Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-002",
                album_art_source_path=str(artwork_path),
            )
        )
        track_b = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00022",
                track_title="Remix B",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Shared Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-002",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Shared Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_a, disc_number=1, track_number=1, sequence_number=1
                    ),
                    ReleaseTrackPlacement(
                        track_id=track_b, disc_number=1, track_number=2, sequence_number=2
                    ),
                ],
            )
        )

        package_path = self.data_root / "shared-package.zip"
        self.service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            media_entries = [name for name in archive.namelist() if name.startswith("media/")]
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        self.assertEqual(len(media_entries), 1)
        self.assertTrue(media_entries[0].startswith("media/track_media/images/"))
        art_paths = [str(row.get("album_art_path") or "").strip() for row in manifest["rows"]]
        self.assertEqual(len([path for path in art_paths if path]), 2)
        self.assertEqual(len({path for path in art_paths if path}), 1)

    def case_inspect_package_reads_manifest_preview(self):
        track_id = self._create_track(isrc="NL-ABC-26-00023", title="Comet", audio=True)
        self._create_release(track_id)
        package_path = self.data_root / "inspect-package.zip"
        self.service.export_package(package_path)

        inspection = self.service.inspect_package(package_path)

        self.assertEqual(inspection.format_name, "package")
        self.assertIn("track_title", inspection.headers)
        self.assertTrue(inspection.preview_rows)
        self.assertTrue(
            any("Packaged media entries detected:" in warning for warning in inspection.warnings)
        )

    def case_package_import_round_trip_restores_media_and_release_artwork(self):
        audio_path = self.data_root / "Pulse.wav"
        audio_path.write_bytes(b"RIFFdemo")
        artwork_path = self.data_root / "pulse.png"
        artwork_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A"
                "0000000D49484452000000010000000108060000001F15C489"
                "0000000D49444154789C63F8FFFF3F0005FE02FEA7D6059F"
                "0000000049454E44AE426082"
            )
        )
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00024",
                track_title="Pulse",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Pulse Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-003",
                audio_file_source_path=str(audio_path),
                album_art_source_path=str(artwork_path),
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Pulse Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc="036000291452",
                artwork_source_path=str(artwork_path),
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )

        package_path = self.data_root / "roundtrip-package.zip"
        self.service.export_package(package_path)

        new_root = self.data_root / "imported"
        new_root.mkdir(parents=True, exist_ok=True)
        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=new_root).init_db()
            DatabaseSchemaService(new_conn, data_root=new_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, new_root),
                ReleaseService(new_conn, new_root),
                CustomFieldDefinitionService(new_conn),
                new_root,
            )

            report = new_service.import_package(
                package_path, options=ExchangeImportOptions(mode="create")
            )

            self.assertEqual(report.failed, 0)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Releases").fetchone()[0], 1)
            audio_ref = new_conn.execute("SELECT audio_file_path FROM Tracks").fetchone()[0]
            track_art_meta = new_service.track_service.get_media_meta(1, "album_art")
            release_art_ref = new_conn.execute("SELECT artwork_path FROM Releases").fetchone()[0]
            self.assertTrue(str(audio_ref or "").strip())
            self.assertTrue(str(track_art_meta.get("path") or "").strip())
            self.assertTrue(str(release_art_ref or "").strip())
        finally:
            new_conn.close()

    def case_package_import_round_trip_restores_shared_album_art_without_child_rewrite(self):
        artwork_path = self.data_root / "shared-roundtrip.png"
        artwork_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A"
                "0000000D49484452000000010000000108060000001F15C489"
                "0000000D49444154789C63F8FFFF3F0005FE02FEA7D6059F"
                "0000000049454E44AE426082"
            )
        )
        track_a = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00027",
                track_title="Shared Import A",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Shared Import Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-006",
                album_art_source_path=str(artwork_path),
            )
        )
        track_b = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00028",
                track_title="Shared Import B",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Shared Import Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-006",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Shared Import Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_a, disc_number=1, track_number=1, sequence_number=1
                    ),
                    ReleaseTrackPlacement(
                        track_id=track_b, disc_number=1, track_number=2, sequence_number=2
                    ),
                ],
            )
        )

        package_path = self.data_root / "shared-roundtrip-package.zip"
        self.service.export_package(package_path)

        new_root = self.data_root / "shared-imported"
        new_root.mkdir(parents=True, exist_ok=True)
        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=new_root).init_db()
            DatabaseSchemaService(new_conn, data_root=new_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, new_root),
                ReleaseService(new_conn, new_root),
                CustomFieldDefinitionService(new_conn),
                new_root,
            )

            report = new_service.import_package(
                package_path, options=ExchangeImportOptions(mode="create")
            )

            self.assertEqual(report.failed, 0)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 2)
            self.assertEqual(
                new_conn.execute("SELECT album_art_path FROM Tracks ORDER BY id").fetchall(),
                [(None,), (None,)],
            )
            album_art_path = new_conn.execute("SELECT album_art_path FROM Albums").fetchone()[0]
            self.assertTrue(str(album_art_path or "").strip())
            lead_bytes, _ = new_service.track_service.fetch_media_bytes(1, "album_art")
            peer_bytes, _ = new_service.track_service.fetch_media_bytes(2, "album_art")
            self.assertEqual(lead_bytes, artwork_path.read_bytes())
            self.assertEqual(peer_bytes, artwork_path.read_bytes())
        finally:
            new_conn.close()

    def case_package_import_reuses_duplicate_track_rows_and_preserves_source_release_ids(self):
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00029",
                track_title="Shared Across Releases",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Shared Source Album",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-007",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Same Identity Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Same Identity Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-16",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )

        package_path = self.data_root / "duplicate-track-release-package.zip"
        self.service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(len(manifest["rows"]), 2)
        self.assertEqual(
            len({str(row.get("release_id") or "").strip() for row in manifest["rows"] if row}),
            2,
        )

        new_root = self.data_root / "duplicate-track-release-imported"
        new_root.mkdir(parents=True, exist_ok=True)
        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=new_root).init_db()
            DatabaseSchemaService(new_conn, data_root=new_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, new_root),
                ReleaseService(new_conn, new_root),
                CustomFieldDefinitionService(new_conn),
                new_root,
            )

            report = new_service.import_package(
                package_path, options=ExchangeImportOptions(mode="create")
            )

            self.assertEqual(report.failed, 0)
            self.assertEqual(report.passed, 2)
            self.assertEqual(len(report.created_tracks), 1)
            self.assertEqual(report.updated_tracks, [])
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Releases").fetchone()[0], 2)
            self.assertEqual(
                new_conn.execute("SELECT COUNT(*) FROM ReleaseTracks").fetchone()[0], 2
            )
            self.assertEqual(
                new_conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM Releases
                    WHERE title='Same Identity Release' AND upc='036000291452'
                    """
                ).fetchone()[0],
                2,
            )
        finally:
            new_conn.close()

    def case_package_round_trip_preserves_database_backed_media_modes(self):
        audio_path = self.data_root / "blob-track.wav"
        audio_path.write_bytes(b"RIFFblobtrack")
        artwork_path = self.data_root / "blob-release.png"
        artwork_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A"
                "0000000D49484452000000010000000108060000001F15C489"
                "0000000D49444154789C63F8FFFF3F0005FE02FEA7D6059F"
                "0000000049454E44AE426082"
            )
        )
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00026",
                track_title="Blob Orbit",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Blob Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Ambient",
                catalog_number="CAT-005",
                audio_file_source_path=str(audio_path),
                audio_file_storage_mode="database",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Blob Release",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc="036000291452",
                artwork_source_path=str(artwork_path),
                artwork_storage_mode="database",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )

        package_path = self.data_root / "blob-package.zip"
        self.service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        self.assertTrue(any(name.startswith("media/embedded/track/") for name in names))
        self.assertTrue(any(name.startswith("media/embedded/release/") for name in names))
        self.assertEqual(manifest["rows"][0]["audio_file_storage_mode"], "database")
        self.assertEqual(manifest["rows"][0]["release_artwork_storage_mode"], "database")

        new_root = self.data_root / "blob-imported"
        new_root.mkdir(parents=True, exist_ok=True)
        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=new_root).init_db()
            DatabaseSchemaService(new_conn, data_root=new_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, new_root),
                ReleaseService(new_conn, new_root),
                CustomFieldDefinitionService(new_conn),
                new_root,
            )

            report = new_service.import_package(
                package_path, options=ExchangeImportOptions(mode="create")
            )

            self.assertEqual(report.failed, 0)
            self.assertEqual(
                new_conn.execute(
                    "SELECT audio_file_storage_mode, audio_file_path FROM Tracks"
                ).fetchone(),
                ("database", None),
            )
            self.assertEqual(
                new_conn.execute(
                    "SELECT artwork_storage_mode, artwork_path FROM Releases"
                ).fetchone(),
                ("database", None),
            )
            audio_bytes, _ = new_service.track_service.fetch_media_bytes(1, "audio_file")
            artwork_bytes, _ = new_service.release_service.fetch_artwork_bytes(1)
            self.assertEqual(audio_bytes, b"RIFFblobtrack")
            self.assertEqual(artwork_bytes, artwork_path.read_bytes())
        finally:
            new_conn.close()

    def case_package_import_supports_legacy_relative_media_without_index(self):
        package_path = self.data_root / "legacy-package.zip"
        rows = [
            {
                "track_id": 1,
                "isrc": "NL-ABC-26-00025",
                "track_title": "Legacy Track",
                "artist_name": "Moonwake",
                "additional_artists": "",
                "album_title": "Legacy Release",
                "release_date": "2026-03-15",
                "track_length_sec": 180,
                "track_length_hms": "00:03:00",
                "iswc": "",
                "upc": "036000291452",
                "genre": "Ambient",
                "catalog_number": "CAT-004",
                "buma_work_number": "",
                "composer": "",
                "publisher": "",
                "comments": "",
                "lyrics": "",
                "audio_file_path": "track_media/audio/legacy.wav",
                "album_art_path": "track_media/images/legacy.png",
                "release_id": "",
                "release_title": "Legacy Release",
                "release_version_subtitle": "",
                "release_primary_artist": "Moonwake",
                "release_album_artist": "Moonwake",
                "release_type": "album",
                "release_date_release": "2026-03-15",
                "release_original_release_date": "",
                "release_label": "",
                "release_sublabel": "",
                "release_catalog_number": "CAT-004",
                "release_upc": "036000291452",
                "release_barcode_validation_status": "valid",
                "release_territory": "",
                "release_explicit_flag": 0,
                "release_notes": "",
                "release_artwork_path": "track_media/images/legacy.png",
                "disc_number": 1,
                "track_number": 1,
                "sequence_number": 1,
                "license_files": "",
            }
        ]
        payload = {
            "schema_version": 1,
            "exported_at": "2026-03-15T22:44:12",
            "columns": list(rows[0].keys()),
            "rows": rows,
            "custom_field_defs": [],
            "packaged_media": True,
        }
        with ZipFile(package_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(payload, indent=2, ensure_ascii=False))
            archive.writestr("media/track_media/audio/legacy.wav", b"RIFFlegacy")
            archive.writestr(
                "media/track_media/images/legacy.png",
                bytes.fromhex(
                    "89504E470D0A1A0A"
                    "0000000D49484452000000010000000108060000001F15C489"
                    "0000000D49444154789C63F8FFFF3F0005FE02FEA7D6059F"
                    "0000000049454E44AE426082"
                ),
            )

        new_root = self.data_root / "legacy-imported"
        new_root.mkdir(parents=True, exist_ok=True)
        new_conn = sqlite3.connect(":memory:")
        try:
            DatabaseSchemaService(new_conn, data_root=new_root).init_db()
            DatabaseSchemaService(new_conn, data_root=new_root).migrate_schema()
            new_service = ExchangeService(
                new_conn,
                TrackService(new_conn, new_root),
                ReleaseService(new_conn, new_root),
                CustomFieldDefinitionService(new_conn),
                new_root,
            )

            report = new_service.import_package(
                package_path, options=ExchangeImportOptions(mode="create")
            )

            self.assertEqual(report.failed, 0)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
            self.assertTrue(
                str(
                    new_conn.execute("SELECT audio_file_path FROM Tracks").fetchone()[0] or ""
                ).strip()
            )
            self.assertTrue(
                str(
                    new_conn.execute("SELECT artwork_path FROM Releases").fetchone()[0] or ""
                ).strip()
            )
        finally:
            new_conn.close()

    def case_inspect_csv_suggests_known_headers(self):
        csv_path = self.data_root / "headers.csv"
        csv_path.write_text(
            "track_title,artist_name,custom::Mood\nOrbit,Moonwake,Dreamy\n", encoding="utf-8"
        )

        inspection = self.service.inspect_csv(csv_path)

        self.assertEqual(inspection.headers, ["track_title", "artist_name", "custom::Mood"])
        self.assertEqual(
            inspection.preview_rows,
            [{"track_title": "Orbit", "artist_name": "Moonwake", "custom::Mood": "Dreamy"}],
        )
        self.assertEqual(inspection.suggested_mapping["track_title"], "track_title")
        self.assertEqual(inspection.suggested_mapping["artist_name"], "artist_name")
        self.assertEqual(inspection.suggested_mapping["custom::Mood"], "custom::Mood")

    def case_inspect_csv_preserves_quoted_commas(self):
        csv_path = self.data_root / "quoted-commas.csv"
        csv_path.write_text(
            "track_title,artist_name,comments\n" '"Orbit, Pt. 1",Moonwake,"Dreamy, wide mix"\n',
            encoding="utf-8",
        )

        inspection = self.service.inspect_csv(csv_path)

        self.assertEqual(inspection.headers, ["track_title", "artist_name", "comments"])
        self.assertEqual(
            inspection.preview_rows,
            [
                {
                    "track_title": "Orbit, Pt. 1",
                    "artist_name": "Moonwake",
                    "comments": "Dreamy, wide mix",
                }
            ],
        )

    def case_inspect_csv_detects_semicolon_delimiter(self):
        csv_path = self.data_root / "semicolon-headers.csv"
        csv_path.write_text(
            "track_title;artist_name;isrc\nOrbit;Moonwake;NL-ABC-26-00033\n",
            encoding="utf-8",
        )

        inspection = self.service.inspect_csv(csv_path)

        self.assertEqual(inspection.headers, ["track_title", "artist_name", "isrc"])
        self.assertEqual(
            inspection.preview_rows,
            [{"track_title": "Orbit", "artist_name": "Moonwake", "isrc": "NL-ABC-26-00033"}],
        )
        self.assertEqual(inspection.resolved_delimiter, ";")

    def case_inspect_csv_detects_tab_delimiter(self):
        csv_path = self.data_root / "tab-headers.csv"
        csv_path.write_text(
            "track_title\tartist_name\tcomments\nOrbit\tMoonwake\tTabbed import\n",
            encoding="utf-8",
        )

        inspection = self.service.inspect_csv(csv_path)

        self.assertEqual(inspection.headers, ["track_title", "artist_name", "comments"])
        self.assertEqual(
            inspection.preview_rows,
            [
                {
                    "track_title": "Orbit",
                    "artist_name": "Moonwake",
                    "comments": "Tabbed import",
                }
            ],
        )
        self.assertEqual(inspection.resolved_delimiter, "\t")

    def case_import_csv_detects_pipe_delimiter(self):
        csv_path = self.data_root / "pipe-import.csv"
        csv_path.write_text(
            "track_title|artist_name|isrc|comments\n"
            "Orbit|Moonwake|NL-ABC-26-00034|Pipe import\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "isrc": "isrc",
                "comments": "comments",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT t.track_title, COALESCE(a.name, ''), t.comments
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.id=?
                """,
                (report.created_tracks[0],),
            ).fetchone(),
            ("Orbit", "Moonwake", "Pipe import"),
        )

    def case_custom_csv_delimiter_refresh_and_import_preserve_quoted_values(self):
        csv_path = self.data_root / "caret-import.csv"
        csv_path.write_text(
            "track_title^artist_name^comments\n" '"Orbit^Pt. 1"^Moonwake^"Dreamy^wide mix"\n',
            encoding="utf-8",
        )

        inspection = self.service.inspect_csv(csv_path, delimiter="^")
        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "comments": "comments",
            },
            options=ExchangeImportOptions(mode="create"),
            delimiter=inspection.resolved_delimiter,
        )

        self.assertEqual(inspection.resolved_delimiter, "^")
        self.assertEqual(
            inspection.preview_rows,
            [
                {
                    "track_title": "Orbit^Pt. 1",
                    "artist_name": "Moonwake",
                    "comments": "Dreamy^wide mix",
                }
            ],
        )
        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT track_title, comments FROM Tracks WHERE id=?",
                (report.created_tracks[0],),
            ).fetchone(),
            ("Orbit^Pt. 1", "Dreamy^wide mix"),
        )

    def case_import_csv_rejects_invalid_explicit_delimiter(self):
        csv_path = self.data_root / "invalid-delimiter.csv"
        csv_path.write_text("track_title,artist_name\nOrbit,Moonwake\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "single non-newline"):
            self.service.inspect_csv(csv_path, delimiter="||")
        with self.assertRaisesRegex(ValueError, "single non-newline"):
            self.service.import_csv(
                csv_path,
                mapping={"track_title": "track_title", "artist_name": "artist_name"},
                options=ExchangeImportOptions(mode="create"),
                delimiter="||",
            )

    def case_import_csv_normalizes_hms_track_length_target(self):
        csv_path = self.data_root / "duration-import.csv"
        csv_path.write_text(
            "track_title,artist_name,track_length_sec\n"
            "Orbit,Moonwake,12:34:56\n"
            "Pulse,Moonwake,180\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "track_length_sec": "track_length_sec",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 2)
        self.assertEqual(
            self.conn.execute(
                "SELECT track_title, track_length_sec FROM Tracks ORDER BY id"
            ).fetchall(),
            [("Orbit", 45296), ("Pulse", 180)],
        )

    def case_import_csv_invalid_track_length_text_still_fails_row(self):
        csv_path = self.data_root / "invalid-duration-import.csv"
        csv_path.write_text(
            "track_title,artist_name,track_length_sec\nOrbit,Moonwake,not-a-duration\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "track_length_sec": "track_length_sec",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.failed, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0],
            0,
        )

    def case_import_xlsx_normalizes_track_length_target_values(self):
        xlsx_path = self.data_root / "duration-import.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["track_title", "artist_name", "track_length_sec"])
        sheet.append(["Orbit", "Moonwake", "12:34:56"])
        sheet.append(["Pulse", "Moonwake", time(1, 2, 3)])
        sheet.append(["Drift", "Moonwake", timedelta(hours=2, minutes=3, seconds=4)])
        sheet.append(["Signal", "Moonwake", 180])
        workbook.save(xlsx_path)

        report = self.service.import_xlsx(
            xlsx_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "track_length_sec": "track_length_sec",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 4)
        self.assertEqual(
            self.conn.execute(
                "SELECT track_title, track_length_sec FROM Tracks ORDER BY id"
            ).fetchall(),
            [("Orbit", 45296), ("Pulse", 3723), ("Drift", 7384), ("Signal", 180)],
        )

    def case_import_csv_normalizes_allowed_title_fields_after_mapping_and_preserves_codes(self):
        self.custom_defs.ensure_fields([{"name": "Mood", "field_type": "text"}])
        csv_path = self.data_root / "title-name-normalization.csv"
        csv_path.write_text(
            "Song Name,Lead Artist,Guest Artists,Album Name,Release Name,Release Primary,Release Album Artist,Track Length,ISRC Code,ISWC Code,UPC Code,Cat No,Release Cat No,Release UPC,Mood Source\n"
            '"DJ/MC BATTLE",JOHN DOE,"JANE DOE, DJ/MC CREW",THE FOREST OF INFINITE IMAGINATION,THE FOREST OF INFINITE IMAGINATION,JOHN DOE,DJ/MC CREW,180,NL-ABC-25-00001,T-123.456.789-0,036000291452,CAT-001,REL-001,036000291452,LOUD\n',
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "Song Name": "track_title",
                "Lead Artist": "artist_name",
                "Guest Artists": "additional_artists",
                "Album Name": "album_title",
                "Release Name": "release_title",
                "Release Primary": "release_primary_artist",
                "Release Album Artist": "release_album_artist",
                "Track Length": "track_length_sec",
                "ISRC Code": "isrc",
                "ISWC Code": "iswc",
                "UPC Code": "upc",
                "Cat No": "catalog_number",
                "Release Cat No": "release_catalog_number",
                "Release UPC": "release_upc",
                "Mood Source": "custom::Mood",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        track_id = report.created_tracks[0]
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        assert snapshot is not None

        self.assertEqual(snapshot.track_title, "DJ/MC Battle")
        self.assertEqual(snapshot.artist_name, "John Doe")
        self.assertEqual(sorted(snapshot.additional_artists), ["DJ/MC Crew", "Jane Doe"])
        self.assertEqual(snapshot.album_title, "The Forest of Infinite Imagination")
        self.assertEqual(snapshot.isrc, "NL-ABC-25-00001")
        self.assertEqual(snapshot.iswc, "T-123.456.789-0")
        self.assertEqual(snapshot.upc, "036000291452")
        self.assertEqual(snapshot.catalog_number, "CAT-001")
        self.assertEqual(
            self._fetch_release_row_for_track(track_id),
            (
                "The Forest of Infinite Imagination",
                "John Doe",
                "DJ/MC Crew",
                "REL-001",
                "036000291452",
            ),
        )
        self.assertEqual(self._fetch_custom_value(track_id, "Mood"), "LOUD")

    def case_import_xlsx_normalizes_allowed_title_fields_and_preserves_codes(self):
        xlsx_path = self.data_root / "title-name-normalization.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(
            [
                "track_title",
                "artist_name",
                "additional_artists",
                "album_title",
                "release_title",
                "release_primary_artist",
                "release_album_artist",
                "track_length_sec",
                "isrc",
                "iswc",
                "upc",
                "catalog_number",
                "release_catalog_number",
                "release_upc",
            ]
        )
        sheet.append(
            [
                "DJ/MC BATTLE",
                "JOHN DOE",
                "JANE DOE, DJ/MC CREW",
                "THE FOREST OF INFINITE IMAGINATION",
                "THE FOREST OF INFINITE IMAGINATION",
                "JOHN DOE",
                "DJ/MC CREW",
                180,
                "NL-ABC-25-00002",
                "T-123.456.789-0",
                "036000291452",
                "CAT-002",
                "REL-002",
                "036000291452",
            ]
        )
        workbook.save(xlsx_path)

        report = self.service.import_xlsx(
            xlsx_path,
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        track_id = report.created_tracks[0]
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        assert snapshot is not None

        self.assertEqual(snapshot.track_title, "DJ/MC Battle")
        self.assertEqual(snapshot.artist_name, "John Doe")
        self.assertEqual(sorted(snapshot.additional_artists), ["DJ/MC Crew", "Jane Doe"])
        self.assertEqual(snapshot.album_title, "The Forest of Infinite Imagination")
        self.assertEqual(snapshot.isrc, "NL-ABC-25-00002")
        self.assertEqual(snapshot.iswc, "T-123.456.789-0")
        self.assertEqual(snapshot.upc, "036000291452")
        self.assertEqual(snapshot.catalog_number, "CAT-002")
        self.assertEqual(
            self._fetch_release_row_for_track(track_id),
            (
                "The Forest of Infinite Imagination",
                "John Doe",
                "DJ/MC Crew",
                "REL-002",
                "036000291452",
            ),
        )

    def case_import_json_normalizes_allowed_title_fields_and_preserves_existing_case_and_codes(
        self,
    ):
        json_path = self.data_root / "title-name-normalization.json"
        payload = {
            "schema_version": 1,
            "columns": [
                "track_title",
                "artist_name",
                "additional_artists",
                "album_title",
                "release_title",
                "release_primary_artist",
                "release_album_artist",
                "track_length_sec",
                "isrc",
                "iswc",
                "upc",
                "catalog_number",
                "release_catalog_number",
                "release_upc",
            ],
            "rows": [
                {
                    "track_title": "DJ/MC BATTLE",
                    "artist_name": "JOHN DOE",
                    "additional_artists": "JANE DOE, DJ/MC CREW",
                    "album_title": "THE FOREST OF INFINITE IMAGINATION",
                    "release_title": "THE FOREST OF INFINITE IMAGINATION",
                    "release_primary_artist": "JOHN DOE",
                    "release_album_artist": "DJ/MC CREW",
                    "track_length_sec": 180,
                    "isrc": "NL-ABC-25-00003",
                    "iswc": "T-123.456.789-0",
                    "upc": "036000291452",
                    "catalog_number": "CAT-003",
                    "release_catalog_number": "REL-003",
                    "release_upc": "036000291452",
                },
                {
                    "track_title": "Already Fine",
                    "artist_name": "deadmau5",
                    "additional_artists": "Jane Doe",
                    "album_title": "Night Drive",
                    "release_title": "Night Drive",
                    "release_primary_artist": "deadmau5",
                    "release_album_artist": "deadmau5",
                    "track_length_sec": 181,
                    "isrc": "NL-ABC-25-00004",
                    "iswc": "T-223.456.789-0",
                    "upc": "042100005264",
                    "catalog_number": "CAT-004",
                    "release_catalog_number": "REL-004",
                    "release_upc": "042100005264",
                },
            ],
            "custom_field_defs": [],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        report = self.service.import_json(json_path, options=ExchangeImportOptions(mode="create"))

        self.assertEqual(report.passed, 2)
        self.assertEqual(report.failed, 0)

        first_snapshot = self.track_service.fetch_track_snapshot(report.created_tracks[0])
        second_snapshot = self.track_service.fetch_track_snapshot(report.created_tracks[1])
        assert first_snapshot is not None
        assert second_snapshot is not None

        self.assertEqual(first_snapshot.track_title, "DJ/MC Battle")
        self.assertEqual(first_snapshot.artist_name, "John Doe")
        self.assertEqual(sorted(first_snapshot.additional_artists), ["DJ/MC Crew", "Jane Doe"])
        self.assertEqual(first_snapshot.album_title, "The Forest of Infinite Imagination")
        self.assertEqual(first_snapshot.isrc, "NL-ABC-25-00003")
        self.assertEqual(first_snapshot.iswc, "T-123.456.789-0")
        self.assertEqual(first_snapshot.upc, "036000291452")
        self.assertEqual(first_snapshot.catalog_number, "CAT-003")
        self.assertEqual(
            self._fetch_release_row_for_track(first_snapshot.track_id),
            (
                "The Forest of Infinite Imagination",
                "John Doe",
                "DJ/MC Crew",
                "REL-003",
                "036000291452",
            ),
        )

        self.assertEqual(second_snapshot.track_title, "Already Fine")
        self.assertEqual(second_snapshot.artist_name, "deadmau5")
        self.assertEqual(second_snapshot.additional_artists, ["Jane Doe"])
        self.assertEqual(second_snapshot.album_title, "Night Drive")
        self.assertEqual(second_snapshot.isrc, "NL-ABC-25-00004")
        self.assertEqual(second_snapshot.iswc, "T-223.456.789-0")
        self.assertEqual(second_snapshot.upc, "042100005264")
        self.assertEqual(second_snapshot.catalog_number, "CAT-004")
        self.assertEqual(
            self._fetch_release_row_for_track(second_snapshot.track_id),
            (
                "Night Drive",
                "deadmau5",
                "deadmau5",
                "REL-004",
                "042100005264",
            ),
        )

    def case_normalize_text_target_restores_only_exact_compound_spans(self):
        self.assertEqual(
            self.service._normalize_text_target("track_title", "AC/DC LIVE SESSION"),
            "AC/DC Live Session",
        )
        self.assertEqual(
            self.service._normalize_text_target("artist_name", "R&B UNIT"),
            "R&B Unit",
        )
        self.assertEqual(
            self.service._normalize_text_target("album_title", "THE R&B SESSIONS"),
            "The R&B Sessions",
        )
        self.assertEqual(
            self.service._normalize_text_target("release_album_artist", "AC/DC"),
            "AC/DC",
        )
        self.assertEqual(
            self.service._normalize_additional_artists_target("DJ/MC CREW, JANE DOE"),
            "DJ/MC Crew, Jane Doe",
        )
        self.assertEqual(
            self.service._normalize_text_target("track_title", "AC/DC Live"),
            "AC/DC Live",
        )
        self.assertEqual(
            self.service._normalize_text_target("comments", "AC/DC LIVE"),
            "AC/DC LIVE",
        )
        self.assertEqual(
            self.service._normalize_text_target("custom::Mood", "R&B NIGHTS"),
            "R&B NIGHTS",
        )

    def case_merge_mode_matches_case_only_title_and_artist_differences(self):
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00035",
                track_title="Orbit",
                artist_name="Moonwake",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
                comments=None,
            )
        )
        csv_path = self.data_root / "merge-case-import.csv"
        csv_path.write_text(
            "track_title,artist_name,comments\nORBIT,MOONWAKE,Imported note\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "comments": "comments",
            },
            options=ExchangeImportOptions(
                mode="merge",
                match_by_internal_id=False,
                match_by_isrc=False,
                match_by_upc_title=False,
                heuristic_match=False,
            ),
        )

        self.assertEqual(report.updated_tracks, [track_id])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Artists").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT t.track_title, a.name, t.comments
                FROM Tracks t
                JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.id=?
                """,
                (track_id,),
            ).fetchone(),
            ("Orbit", "Moonwake", "Imported note"),
        )

    def case_merge_mode_matches_case_only_upc_title_lookup(self):
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00036",
                track_title="Orbit",
                artist_name="Moonwake",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre=None,
                comments=None,
            )
        )
        csv_path = self.data_root / "merge-upc-title-import.csv"
        csv_path.write_text(
            "track_title,artist_name,upc,comments\nORBIT,Ignored Artist,036000291452,UPC title match\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "upc": "upc",
                "comments": "comments",
            },
            options=ExchangeImportOptions(
                mode="merge",
                match_by_internal_id=False,
                match_by_isrc=False,
                match_by_upc_title=True,
                heuristic_match=False,
            ),
        )

        self.assertEqual(report.updated_tracks, [track_id])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT t.track_title, a.name, t.comments
                FROM Tracks t
                JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.id=?
                """,
                (track_id,),
            ).fetchone(),
            ("Orbit", "Moonwake", "UPC title match"),
        )

    def case_merge_mode_does_not_auto_merge_ambiguous_case_normalized_match(self):
        for suffix in ("37", "38"):
            self.track_service.create_track(
                TrackCreatePayload(
                    isrc=f"NL-ABC-26-000{suffix}",
                    track_title="Orbit",
                    artist_name="Moonwake",
                    additional_artists=[],
                    album_title=None,
                    release_date=None,
                    track_length_sec=180,
                    iswc=None,
                    upc=None,
                    genre=None,
                )
            )
        csv_path = self.data_root / "merge-ambiguous-import.csv"
        csv_path.write_text(
            "track_title,artist_name,comments\nORBIT,COSMOWYN,Ambiguous match\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "comments": "comments",
            },
            options=ExchangeImportOptions(
                mode="merge",
                match_by_internal_id=False,
                match_by_isrc=False,
                match_by_upc_title=False,
                heuristic_match=False,
            ),
        )

        self.assertEqual(report.updated_tracks, [])
        self.assertEqual(len(report.created_tracks), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 3)

    def case_supported_import_targets_include_active_non_blob_custom_fields(self):
        self.custom_defs.ensure_fields(
            [
                {"name": "Mood", "field_type": "text"},
                {"name": "Artwork", "field_type": "blob_image"},
            ]
        )

        targets = self.service.supported_import_targets()

        self.assertIn("custom::Mood", targets)
        self.assertNotIn("custom::Artwork", targets)
        self.assertEqual(len(targets), len(set(targets)))

    def case_import_csv_maps_arbitrary_source_column_to_active_custom_field(self):
        self.custom_defs.ensure_fields([{"name": "Mood", "field_type": "text"}])
        csv_path = self.data_root / "custom-mapping-import.csv"
        csv_path.write_text(
            "Title,Artist,Energy\nOrbit,Moonwake,Dreamy\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "Title": "track_title",
                "Artist": "artist_name",
                "Energy": "custom::Mood",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT cfd.name, cfv.value
                FROM CustomFieldValues cfv
                JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
                """
            ).fetchall(),
            [("Mood", "Dreamy")],
        )

    def case_import_csv_reuses_same_name_existing_custom_field_type(self):
        self.custom_defs.ensure_fields(
            [
                {
                    "name": "Distribution Status",
                    "field_type": "dropdown",
                    "options": json.dumps(["Draft", "Approved"]),
                }
            ]
        )
        csv_path = self.data_root / "distribution-status-import.csv"
        csv_path.write_text(
            "track_title,artist_name,custom::Distribution Status\n" "Orbit,Moonwake,Approved\n",
            encoding="utf-8",
        )

        report = self.service.import_csv(
            csv_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
                "custom::Distribution Status": "custom::Distribution Status",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM CustomFieldDefs WHERE name='Distribution Status'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT field_type FROM CustomFieldDefs WHERE name='Distribution Status'"
            ).fetchone()[0],
            "dropdown",
        )
        self.assertEqual(
            self.conn.execute(
                """
                SELECT cfv.value
                FROM CustomFieldValues cfv
                JOIN CustomFieldDefs cfd ON cfd.id = cfv.field_def_id
                WHERE cfd.name='Distribution Status'
                """
            ).fetchone()[0],
            "Approved",
        )

    def case_import_json_respects_mapping_when_skipping_custom_field(self):
        json_path = self.data_root / "skip-json-field.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "columns": ["track_title", "artist_name", "custom::Mood"],
                    "rows": [
                        {
                            "track_title": "Orbit",
                            "artist_name": "Moonwake",
                            "custom::Mood": "Dreamy",
                        }
                    ],
                    "custom_field_defs": [],
                }
            ),
            encoding="utf-8",
        )

        report = self.service.import_json(
            json_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
            0,
        )

    def case_import_package_respects_mapping_when_skipping_custom_field(self):
        package_path = self.data_root / "skip-package-field.zip"
        manifest = {
            "schema_version": 1,
            "columns": ["track_title", "artist_name", "custom::Mood"],
            "rows": [
                {
                    "track_title": "Orbit",
                    "artist_name": "Moonwake",
                    "custom::Mood": "Dreamy",
                }
            ],
            "custom_field_defs": [],
            "packaged_media": False,
            "packaged_media_index": {},
        }
        with ZipFile(package_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))

        report = self.service.import_package(
            package_path,
            mapping={
                "track_title": "track_title",
                "artist_name": "artist_name",
            },
            options=ExchangeImportOptions(mode="create"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()

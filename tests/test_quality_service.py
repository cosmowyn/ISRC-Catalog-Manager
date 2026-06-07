import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.domain.codes import barcode_validation_status, to_compact_isrc
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.quality import QualityDashboardService, QualityIssue, QualityScanResult
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.services import (
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    TrackCreatePayload,
    TrackService,
)
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class QualityDashboardServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.custom_defs = CustomFieldDefinitionService(self.conn)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(self.conn)
        self.asset_service = AssetService(self.conn, self.data_root)
        self.service = QualityDashboardService(
            self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            data_root=self.data_root,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(
        self, *, isrc: str = "", title: str = "Orbit", album: str | None = "Orbit Release"
    ) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Moonwake",
                additional_artists=[],
                album_title=album,
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
                buma_work_number=None,
                composer=None,
                publisher=None,
                comments=None,
                lyrics=None,
                audio_file_source_path=None,
                album_art_source_path=None,
            )
        )

    def test_scan_ignores_legacy_license_archive_rows(self):
        track_id = self._create_track(isrc="NL-ABC-26-00090")
        self.conn.execute(
            "INSERT INTO Licensees(id, name) VALUES (?, ?)",
            (1, "Broken Label"),
        )
        self.conn.execute(
            """
            INSERT INTO Licenses(id, track_id, licensee_id, file_path, filename)
            VALUES (?, ?, ?, ?, ?)
            """,
            (1, track_id + 999, 1, "licenses/orphaned-license.pdf", "orphaned-license.pdf"),
        )

        result = self.service.scan()
        self.assertNotIn("orphaned_license", result.counts_by_type)

    def test_scan_reports_expected_issues(self):
        track_id = self._create_track(isrc="")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                upc=None,
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        self.conn.execute(
            "UPDATE Releases SET artwork_path='release_media/images/missing.png' WHERE id=?",
            (release_id,),
        )
        self.conn.execute(
            "UPDATE Tracks SET audio_file_path='track_media/audio/missing.wav' WHERE id=?",
            (track_id,),
        )
        field = self.custom_defs.ensure_fields(
            [{"name": "Mood", "field_type": "text", "options": json.dumps({"required": True})}]
        )[0]
        self.assertIsNotNone(field)

        result = self.service.scan()
        issue_types = {issue.issue_type for issue in result.issues}

        self.assertIn("missing_isrc", issue_types)
        self.assertIn("missing_release_upc", issue_types)
        self.assertIn("broken_media_reference", issue_types)
        self.assertIn("broken_release_artwork_reference", issue_types)
        self.assertIn("missing_required_custom_field", issue_types)

    def test_scan_reports_metadata_ordering_and_custom_field_edge_issues(self):
        first_track_id = self._create_track(isrc="NL-ABC-26-00401", title="First Edge")
        second_track_id = self._create_track(isrc="NL-ABC-26-00402", title="Second Edge")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_releases_reldate_check_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_releases_reldate_check_upd")
        self.conn.execute("DROP INDEX IF EXISTS idx_tracks_isrc_unique")
        self.conn.execute("DROP INDEX IF EXISTS idx_tracks_isrc_compact_unique")
        self.conn.execute(
            """
            UPDATE Tracks
            SET track_title='',
                main_artist_party_id=0,
                isrc='NL-ABC-26-00499',
                isrc_compact='STALE',
                release_date='31/31/2026',
                audio_file_path='database/audio.wav',
                audio_file_storage_mode='database'
            WHERE id=?
            """,
            (first_track_id,),
        )
        self.conn.execute(
            "UPDATE Tracks SET isrc='NL-ABC-26-00499' WHERE id=?",
            (second_track_id,),
        )

        duplicate_order_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Ordering Edge",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=first_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.conn.execute("DROP INDEX IF EXISTS idx_release_tracks_order_unique")
        self.conn.execute(
            """
            INSERT INTO ReleaseTracks(release_id, track_id, disc_number, track_number, sequence_number)
            VALUES (?, ?, 1, 1, 2)
            """,
            (duplicate_order_release_id, second_track_id),
        )

        first_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Edge A",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="EDGE-CAT",
            )
        )
        second_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Edge B",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="EDGE-CAT",
            )
        )
        checksum_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Edge Checksum",
                primary_artist="Moonwake",
                release_type="single",
                release_date="2026-03-15",
            )
        )
        self.conn.execute(
            """
            UPDATE Releases
            SET title='',
                primary_artist='',
                release_date='not-a-date',
                upc='12345',
                barcode_validation_status='stale',
                artwork_path=''
            WHERE id=?
            """,
            (first_release_id,),
        )
        self.conn.execute(
            "UPDATE Releases SET upc='036000291453', barcode_validation_status='stale' WHERE id=?",
            (checksum_release_id,),
        )
        self.conn.execute(
            "UPDATE Releases SET artwork_path='database/cover.jpg', artwork_storage_mode='database' WHERE id=?",
            (second_release_id,),
        )

        self.conn.execute("""
            INSERT INTO CustomFieldDefs(name, field_type, options, active)
            VALUES ('Malformed Options', 'text', '{', 1)
            """)
        blob_field = self.custom_defs.ensure_fields(
            [
                {
                    "name": "Required Image",
                    "field_type": "blob_image",
                    "options": json.dumps({"required": True}),
                }
            ]
        )[0]
        self.assertEqual(blob_field["field_type"], "blob_image")

        result = self.service.scan()
        issue_types = {issue.issue_type for issue in result.issues}

        self.assertIn("missing_track_title", issue_types)
        self.assertIn("missing_primary_artist", issue_types)
        self.assertIn("invalid_track_release_date", issue_types)
        self.assertIn("derived_isrc_compact_out_of_sync", issue_types)
        self.assertIn("duplicate_isrc", issue_types)
        self.assertIn("missing_release_title", issue_types)
        self.assertIn("missing_release_primary_artist", issue_types)
        self.assertIn("invalid_release_date", issue_types)
        self.assertIn("invalid_release_upc_format", issue_types)
        self.assertIn("invalid_release_upc_checksum", issue_types)
        self.assertIn("release_barcode_status_out_of_sync", issue_types)
        self.assertIn("duplicate_release_catalog_number", issue_types)
        self.assertIn("disc_track_conflict", issue_types)
        self.assertIn("missing_required_custom_field", issue_types)
        self.assertFalse(
            any(
                issue.issue_type == "broken_media_reference" and issue.track_id == first_track_id
                for issue in result.issues
            )
        )
        self.assertFalse(
            any(
                issue.issue_type == "broken_release_artwork_reference"
                and issue.release_id == second_release_id
                for issue in result.issues
            )
        )

    def test_normalize_dates_fix_updates_invalid_values(self):
        track_id = self._create_track(isrc="NL-ABC-26-00001")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")
        self.conn.execute("UPDATE Tracks SET release_date='15/03/2026' WHERE id=?", (track_id,))
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="15-03-2026",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        self.assertGreater(release_id, 0)

        message = self.service.apply_fix("normalize_dates")

        self.assertIn("Normalized", message)
        self.assertEqual(
            self.conn.execute("SELECT release_date FROM Tracks WHERE id=?", (track_id,)).fetchone()[
                0
            ],
            "2026-03-15",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT release_date FROM Releases WHERE id=?", (release_id,)
            ).fetchone()[0],
            "2026-03-15",
        )

    def test_export_writes_csv_and_json_issue_payloads(self):
        issue = QualityIssue(
            "missing_isrc",
            "warning",
            "Missing ISRC",
            "This track needs an ISRC.",
            "track",
            17,
            track_id=17,
            fix_key="regenerate_derived",
        )
        result = QualityScanResult(
            issues=[issue],
            counts_by_severity={"warning": 1},
            counts_by_type={"missing_isrc": 1},
        )
        csv_path = self.data_root / "reports" / "quality.csv"
        json_path = self.data_root / "reports" / "quality.json"

        self.service.export_csv(result, csv_path)
        self.service.export_json(result, json_path)

        csv_text = csv_path.read_text(encoding="utf-8")
        json_payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn("issue_type,severity,title,details", csv_text)
        self.assertIn("missing_isrc,warning,Missing ISRC", csv_text)
        self.assertEqual(json_payload["counts_by_severity"], {"warning": 1})
        self.assertEqual(json_payload["counts_by_type"], {"missing_isrc": 1})
        self.assertEqual(json_payload["issues"][0]["track_id"], 17)

    def test_regenerate_derived_can_scope_track_from_issue_entity(self):
        first_track_id = self._create_track(isrc="NL-ABC-26-00301", title="First Derived")
        second_track_id = self._create_track(isrc="NL-ABC-26-00302", title="Second Derived")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Derived Release",
                primary_artist="Moonwake",
                release_type="album",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=first_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")
        self.conn.execute(
            """
            UPDATE Tracks
            SET isrc_compact=CASE id WHEN ? THEN 'LEGACYA' ELSE 'LEGACYB' END
            WHERE id IN (?, ?)
            """,
            (first_track_id, first_track_id, second_track_id),
        )
        self.conn.execute(
            "UPDATE Releases SET barcode_validation_status='stale' WHERE id=?",
            (release_id,),
        )
        issue = QualityIssue(
            "derived_isrc_compact_out_of_sync",
            "warning",
            "Derived ISRC Out Of Sync",
            "Regenerate the selected track value.",
            "track",
            first_track_id,
            fix_key="regenerate_derived",
        )

        message = self.service.apply_fix("regenerate_derived", issue=issue)

        rows = dict(
            self.conn.execute(
                "SELECT id, isrc_compact FROM Tracks WHERE id IN (?, ?)",
                (first_track_id, second_track_id),
            ).fetchall()
        )
        release_status = self.conn.execute(
            "SELECT barcode_validation_status FROM Releases WHERE id=?",
            (release_id,),
        ).fetchone()[0]
        self.assertEqual(message, "Regenerated derived values for 1 track(s) and 1 release(s).")
        self.assertEqual(rows[first_track_id], to_compact_isrc("NL-ABC-26-00301"))
        self.assertEqual(rows[second_track_id], "LEGACYB")
        self.assertEqual(release_status, barcode_validation_status("036000291452"))

    def test_regenerate_derived_can_scope_release_from_issue_entity(self):
        track_id = self._create_track(isrc="NL-ABC-26-00303", title="Release Scoped")
        first_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Scoped A",
                primary_artist="Moonwake",
                release_type="album",
                upc="036000291452",
            )
        )
        second_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Scoped B",
                primary_artist="Moonwake",
                release_type="album",
                upc="042100005264",
            )
        )
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")
        self.conn.execute("UPDATE Tracks SET isrc_compact='LEGACY' WHERE id=?", (track_id,))
        self.conn.execute(
            "UPDATE Releases SET barcode_validation_status='stale' WHERE id IN (?, ?)",
            (first_release_id, second_release_id),
        )
        issue = QualityIssue(
            "release_barcode_validation_out_of_sync",
            "warning",
            "Release Barcode Out Of Sync",
            "Regenerate the selected release value.",
            "release",
            second_release_id,
            fix_key="regenerate_derived",
        )

        message = self.service.apply_fix("regenerate_derived", issue=issue)

        release_rows = dict(
            self.conn.execute(
                "SELECT id, barcode_validation_status FROM Releases WHERE id IN (?, ?)",
                (first_release_id, second_release_id),
            ).fetchall()
        )
        compact = self.conn.execute(
            "SELECT isrc_compact FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()[0]
        self.assertEqual(message, "Regenerated derived values for 1 track(s) and 1 release(s).")
        self.assertEqual(compact, to_compact_isrc("NL-ABC-26-00303"))
        self.assertEqual(release_rows[first_release_id], "stale")
        self.assertEqual(release_rows[second_release_id], barcode_validation_status("042100005264"))

    def test_normalize_dates_scopes_issue_and_ignores_unparseable_value(self):
        first_track_id = self._create_track(isrc="NL-ABC-26-00304", title="Parseable Date")
        second_track_id = self._create_track(isrc="NL-ABC-26-00305", title="Broken Date")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.conn.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")
        self.conn.execute(
            "UPDATE Tracks SET release_date='2026/03/15' WHERE id=?",
            (first_track_id,),
        )
        self.conn.execute(
            "UPDATE Tracks SET release_date='not-a-date' WHERE id=?",
            (second_track_id,),
        )
        issue = QualityIssue(
            "invalid_track_release_date",
            "warning",
            "Invalid Track Release Date",
            "Only the selected row should be repaired.",
            "track",
            first_track_id,
            fix_key="normalize_dates",
        )

        message = self.service.apply_fix("normalize_dates", issue=issue)

        rows = dict(
            self.conn.execute(
                "SELECT id, release_date FROM Tracks WHERE id IN (?, ?)",
                (first_track_id, second_track_id),
            ).fetchall()
        )
        self.assertEqual(message, "Normalized 1 date value(s).")
        self.assertEqual(rows[first_track_id], "2026-03-15")
        self.assertEqual(rows[second_track_id], "not-a-date")

    def test_normalize_date_handles_empty_and_unknown_formats(self):
        self.assertIsNone(QualityDashboardService._normalize_date(""))
        self.assertIsNone(QualityDashboardService._normalize_date(None))
        self.assertIsNone(QualityDashboardService._normalize_date("March 15 2026"))
        self.assertEqual(
            QualityDashboardService._normalize_date("15-03-2026"),
            "2026-03-15",
        )

    def test_relink_media_reports_unavailable_without_data_root(self):
        service = QualityDashboardService(
            self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            data_root=None,
        )

        message = service.apply_fix("relink_media")

        self.assertEqual(
            message,
            "No data root is configured, so media relinking is unavailable.",
        )

    def test_relink_media_repairs_scoped_audio_album_art_and_release_artwork(self):
        track_id = self._create_track(isrc="NL-ABC-26-00306", title="Relinked Track")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Relinked Release",
                primary_artist="Moonwake",
                release_type="single",
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
        recovered = self.data_root / "recovered"
        recovered.mkdir()
        (recovered / "audio.wav").write_bytes(b"audio")
        (recovered / "cover.jpg").write_bytes(b"cover")
        (recovered / "release.png").write_bytes(b"release")
        self.conn.execute(
            """
            UPDATE Tracks
            SET audio_file_path='missing/audio.wav', album_art_path='missing/cover.jpg'
            WHERE id=?
            """,
            (track_id,),
        )
        self.conn.execute(
            "UPDATE Releases SET artwork_path='missing/release.png' WHERE id=?",
            (release_id,),
        )

        audio_message = self.service.apply_fix(
            "relink_media",
            issue=QualityIssue(
                "broken_media_reference",
                "error",
                "Broken Audio Reference",
                "Audio file moved.",
                "track",
                track_id,
                track_id=track_id,
                fix_key="relink_media",
            ),
        )
        art_message = self.service.apply_fix(
            "relink_media",
            issue=QualityIssue(
                "broken_album_art_reference",
                "error",
                "Broken Album Art Reference",
                "Album art moved.",
                "track",
                track_id,
                track_id=track_id,
                fix_key="relink_media",
            ),
        )
        release_message = self.service.apply_fix(
            "relink_media",
            issue=QualityIssue(
                "broken_release_artwork_reference",
                "error",
                "Broken Release Artwork Reference",
                "Release artwork moved.",
                "release",
                release_id,
                release_id=release_id,
                fix_key="relink_media",
            ),
        )

        track_row = self.conn.execute(
            "SELECT audio_file_path, album_art_path FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()
        release_art = self.conn.execute(
            "SELECT artwork_path FROM Releases WHERE id=?",
            (release_id,),
        ).fetchone()[0]
        self.assertEqual(audio_message, "Relinked 1 media reference(s).")
        self.assertEqual(art_message, "Relinked 1 media reference(s).")
        self.assertEqual(release_message, "Relinked 1 media reference(s).")
        self.assertEqual(track_row, ("recovered/audio.wav", "recovered/cover.jpg"))
        self.assertEqual(release_art, "recovered/release.png")

    def test_relink_media_all_skips_existing_and_unmatched_paths(self):
        track_id = self._create_track(isrc="NL-ABC-26-00307", title="Already Linked")
        existing = self.data_root / "media" / "existing.wav"
        existing.parent.mkdir()
        existing.write_bytes(b"audio")
        self.conn.execute(
            """
            UPDATE Tracks
            SET audio_file_path='media/existing.wav', album_art_path='missing/no-match.jpg'
            WHERE id=?
            """,
            (track_id,),
        )

        message = self.service.apply_fix("relink_media")

        row = self.conn.execute(
            "SELECT audio_file_path, album_art_path FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()
        self.assertEqual(message, "Relinked 0 media reference(s).")
        self.assertEqual(row, ("media/existing.wav", "missing/no-match.jpg"))

    def test_quality_helper_edges_and_generic_relink_scope(self):
        self.assertFalse(self.service._releases_share_linked_album([999]))
        no_root_service = QualityDashboardService(
            self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            data_root=None,
        )
        self.assertIsNone(no_root_service._find_media_by_name("audio.wav"))

        track_id = self._create_track(isrc="NL-ABC-26-00308", title="Generic Relink")
        recovered = self.data_root / "generic-recovered"
        recovered.mkdir()
        (recovered / "audio.wav").write_bytes(b"audio")
        (recovered / "cover.jpg").write_bytes(b"cover")
        self.conn.execute(
            """
            UPDATE Tracks
            SET audio_file_path='missing/audio.wav', album_art_path='missing/cover.jpg'
            WHERE id=?
            """,
            (track_id,),
        )

        message = self.service.apply_fix(
            "relink_media",
            issue=QualityIssue(
                "broken_media_reference",
                "error",
                "Broken Track Media Reference",
                "Both track media fields should be considered.",
                "track",
                track_id,
                track_id=track_id,
                fix_key="relink_media",
            ),
        )

        row = self.conn.execute(
            "SELECT audio_file_path, album_art_path FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()
        self.assertEqual(message, "Relinked 2 media reference(s).")
        self.assertEqual(row, ("generic-recovered/audio.wav", "generic-recovered/cover.jpg"))

        work_id = self.work_service.create_work(WorkPayload(title="Missing Detail Work"))
        with mock.patch.object(self.service.work_service, "fetch_work_detail", return_value=None):
            self.assertFalse(
                any(issue.entity_id == work_id for issue in self.service._work_issues())
            )

        contract_id = self.contract_service.create_contract(
            ContractPayload(title="Missing Detail Contract", status="draft")
        )
        with mock.patch.object(
            self.service.contract_service,
            "fetch_contract_detail",
            return_value=None,
        ):
            self.assertFalse(
                any(issue.entity_id == contract_id for issue in self.service._contract_issues())
            )

    def test_fill_from_release_populates_blank_track_fields(self):
        track_id = self._create_track(isrc="NL-ABC-26-00002")
        self.conn.execute(
            """
            UPDATE Tracks
            SET release_date='', upc='', catalog_number='', album_id=NULL
            WHERE id=?
            """,
            (track_id,),
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Orbit Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-777",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        self.assertGreater(release_id, 0)

        result = self.service.scan()
        issue = next(
            issue
            for issue in result.issues
            if issue.track_id == track_id and issue.fix_key == "fill_from_release"
        )
        message = self.service.apply_fix("fill_from_release", issue=issue)
        row = self.conn.execute(
            "SELECT release_date, upc, catalog_number, album_id FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()

        self.assertIn("Filled blank track values", message)
        self.assertEqual(row[0], "2026-03-15")
        self.assertEqual(row[1], "036000291452")
        self.assertEqual(row[2], "CAT-777")
        self.assertIsNotNone(row[3])

    def test_fill_from_release_selected_issue_only_updates_target_track(self):
        first_track_id = self._create_track(isrc="NL-ABC-26-00003", title="First Orbit")
        second_track_id = self._create_track(isrc="NL-ABC-26-00004", title="Second Orbit")
        self.conn.execute(
            "UPDATE Tracks SET release_date='', upc='', catalog_number='', album_id=NULL WHERE id IN (?, ?)",
            (first_track_id, second_track_id),
        )
        self.release_service.create_release(
            ReleasePayload(
                title="First Orbit Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-101",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=first_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Second Orbit Release",
                primary_artist="Moonwake",
                release_type="album",
                release_date="2026-03-16",
                catalog_number="CAT-202",
                upc="042100005264",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=second_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )

        issue = next(
            issue
            for issue in self.service.scan().issues
            if issue.track_id == first_track_id and issue.fix_key == "fill_from_release"
        )

        self.service.apply_fix("fill_from_release", issue=issue)

        first_row = self.conn.execute(
            "SELECT release_date, upc, catalog_number FROM Tracks WHERE id=?",
            (first_track_id,),
        ).fetchone()
        second_row = self.conn.execute(
            "SELECT release_date, upc, catalog_number FROM Tracks WHERE id=?",
            (second_track_id,),
        ).fetchone()
        self.assertEqual(first_row, ("2026-03-15", "036000291452", "CAT-101"))
        self.assertEqual(second_row, ("", "", ""))

    def test_same_title_duplicate_upc_is_reported_as_info_not_error(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist One",
                upc="8720892724625",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist Two",
                upc="8720892724625",
            )
        )

        result = self.service.scan()
        shared_upc_issues = [
            issue for issue in result.issues if issue.issue_type == "shared_release_upc"
        ]

        self.assertEqual(len(shared_upc_issues), 2)
        self.assertTrue(all(issue.severity == "info" for issue in shared_upc_issues))
        self.assertFalse(
            any(issue.issue_type == "duplicate_release_upc" for issue in result.issues)
        )

    def test_remix_family_duplicate_upc_is_reported_as_info_not_error(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist One",
                release_type="album",
                upc="8720892724625",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite (Remixes)",
                primary_artist="Artist Two",
                release_type="remix_package",
                upc="8720892724625",
            )
        )

        result = self.service.scan()
        shared_upc_issues = [
            issue for issue in result.issues if issue.issue_type == "shared_release_upc"
        ]

        self.assertEqual(len(shared_upc_issues), 2)
        self.assertTrue(all(issue.severity == "info" for issue in shared_upc_issues))
        self.assertFalse(
            any(issue.issue_type == "duplicate_release_upc" for issue in result.issues)
        )

    def test_va_album_track_release_upc_is_reported_as_info_not_error(self):
        first_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00201",
                track_title="North Gate",
                artist_name="Artist One",
                additional_artists=[],
                album_title="Nocturne Compendium",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
                buma_work_number=None,
                composer=None,
                publisher=None,
                comments=None,
                lyrics=None,
                audio_file_source_path=None,
                album_art_source_path=None,
            )
        )
        second_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00202",
                track_title="South Gate",
                artist_name="Artist Two",
                additional_artists=[],
                album_title="Nocturne Compendium",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
                buma_work_number=None,
                composer=None,
                publisher=None,
                comments=None,
                lyrics=None,
                audio_file_source_path=None,
                album_art_source_path=None,
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="North Gate",
                primary_artist="Artist One",
                release_type="single",
                upc="8720892724625",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=first_track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="South Gate",
                primary_artist="Artist Two",
                release_type="single",
                upc="8720892724625",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=second_track_id,
                        disc_number=1,
                        track_number=2,
                        sequence_number=2,
                    )
                ],
            )
        )

        result = self.service.scan()
        shared_upc_issues = [
            issue for issue in result.issues if issue.issue_type == "shared_release_upc"
        ]

        self.assertEqual(len(shared_upc_issues), 2)
        self.assertTrue(all(issue.severity == "info" for issue in shared_upc_issues))
        self.assertTrue(all("same linked album" in issue.details for issue in shared_upc_issues))
        self.assertFalse(
            any(issue.issue_type == "duplicate_release_upc" for issue in result.issues)
        )

    def test_work_quality_rules_prefer_direct_track_work_link_over_shadow_link_table(self):
        work_id = self.work_service.create_work(
            WorkPayload(title="Governed Work", iswc="T-123.456.789-0"),
        )
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00150",
                track_title="Governed Recording",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Governed Release",
                release_date="2026-03-15",
                track_length_sec=180,
                iswc="T-111.111.111-1",
                upc=None,
                genre="Ambient",
                catalog_number=None,
                buma_work_number="BUMA-150",
                composer="Moonwake",
                publisher="Orbit Editions",
                comments=None,
                lyrics=None,
                audio_file_source_path=None,
                album_art_source_path=None,
                work_id=work_id,
            )
        )
        self.assertGreater(track_id, 0)
        self.conn.execute(
            "DELETE FROM WorkTrackLinks WHERE work_id=? AND track_id=?",
            (work_id, track_id),
        )

        issues = self.service.scan().issues
        issue_pairs = {(issue.issue_type, int(issue.entity_id or 0)) for issue in issues}

        self.assertNotIn(("track_missing_linked_work", track_id), issue_pairs)
        self.assertNotIn(("orphaned_work_recording_link", work_id), issue_pairs)

    def test_different_title_duplicate_upc_remains_error(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Release One",
                primary_artist="Artist One",
                upc="8720892724625",
            )
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Release Two",
                primary_artist="Artist Two",
                upc="8720892724625",
            )
        )

        result = self.service.scan()
        duplicate_upc_issues = [
            issue for issue in result.issues if issue.issue_type == "duplicate_release_upc"
        ]

        self.assertEqual(len(duplicate_upc_issues), 2)
        self.assertTrue(all(issue.severity == "error" for issue in duplicate_upc_issues))

    def test_scan_includes_repertoire_contract_rights_and_asset_issues(self):
        track_id = self._create_track(isrc="NL-ABC-26-00088")
        party_a = self.party_service.create_party(
            PartyPayload(legal_name="Echo Music", email="hello@echo.test")
        )
        self.party_service.create_party(PartyPayload(legal_name="Echo Music"))
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Split Trouble",
                iswc="T-101.202.303-4",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter", name="Echo Music", party_id=party_a, share_percent=100
                    )
                ],
                track_ids=[track_id],
            )
        )
        self.conn.execute(
            "UPDATE WorkContributors SET share_percent=40 WHERE work_id=?",
            (work_id,),
        )
        self.contract_service.create_contract(
            ContractPayload(
                title="Unsigned Agreement",
                status="active",
                notice_deadline="2026-03-20",
                track_ids=[track_id],
            )
        )
        self.rights_service.create_right(
            RightPayload(
                title="Unbacked Exclusive",
                right_type="master",
                exclusive_flag=True,
                territory="NL",
                track_id=track_id,
            )
        )
        asset_path = self.data_root / "draft-master.wav"
        asset_path.write_bytes(b"RIFFdemo")
        self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(asset_path),
                approved_for_use=False,
                primary_flag=True,
                track_id=track_id,
            )
        )

        result = self.service.scan()
        issue_types = {issue.issue_type for issue in result.issues}

        self.assertIn("invalid_work_split_total", issue_types)
        self.assertIn("contract_missing_parties", issue_types)
        self.assertIn("contract_missing_signed_final_document", issue_types)
        self.assertIn("rights_missing_source_contract", issue_types)
        self.assertIn("duplicate_party", issue_types)
        self.assertIn("missing_approved_master", issue_types)

    def test_apply_fix_rejects_unknown_fix_key(self):
        with self.assertRaisesRegex(ValueError, "Unknown quality fix: no_such_fix"):
            self.service.apply_fix("no_such_fix")


if __name__ == "__main__":
    unittest.main()

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.quality import QualityDashboardService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.services import (
    CustomFieldDefinitionService,
    DatabaseSchemaService,
    LicenseService,
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

    def test_scan_reports_orphaned_license_when_track_reference_is_broken(self):
        track_id = self._create_track(isrc="NL-ABC-26-00090")
        license_service = LicenseService(self.conn, self.data_root)
        license_pdf = self.data_root / "orphaned-license.pdf"
        license_pdf.write_bytes(b"%PDF-1.4\norphaned license test\n")
        license_id = license_service.add_license(
            track_id=track_id,
            licensee_name="Broken Label",
            source_pdf_path=license_pdf,
        )

        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute(
            "UPDATE Licenses SET track_id=? WHERE id=?",
            (track_id + 999, license_id),
        )
        self.conn.execute("PRAGMA foreign_keys = ON")

        result = self.service.scan()
        orphaned_license_issues = [
            issue for issue in result.issues if issue.issue_type == "orphaned_license"
        ]

        self.assertEqual(len(orphaned_license_issues), 1)
        self.assertEqual(orphaned_license_issues[0].severity, "warning")
        self.assertEqual(result.counts_by_type["orphaned_license"], 1)

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


if __name__ == "__main__":
    unittest.main()

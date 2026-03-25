import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import OwnershipInterestPayload, RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class WorkAndPartyServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track(self, isrc: str, title: str) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Catalog Artist",
                additional_artists=[],
                album_title="Catalog Album",
                release_date="2026-03-16",
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre="Alt",
            )
        )

    def test_work_creation_links_tracks_and_creates_party_records(self):
        track_id = self._create_track("NL-ABC-26-00001", "Night Drive")

        work_id = self.work_service.create_work(
            WorkPayload(
                title="Night Drive",
                iswc="T-123.456.789-0",
                contributors=[
                    WorkContributorPayload(role="songwriter", name="Alex Writer", share_percent=50),
                    WorkContributorPayload(
                        role="composer",
                        name="Jamie Composer",
                        share_percent=50,
                    ),
                    WorkContributorPayload(role="publisher", name="Moonlight Publishing"),
                ],
                track_ids=[track_id],
                work_status="metadata_incomplete",
            )
        )

        detail = self.work_service.fetch_work_detail(work_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.track_ids, [track_id])
        self.assertEqual(len(detail.contributors), 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 3)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM WorkTrackLinks WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT work_id FROM Tracks WHERE id=?", (track_id,)).fetchone()[0],
            work_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM WorkContributionEntries WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            3,
        )

    def test_work_creation_reuses_existing_party_when_contributor_party_id_is_supplied(self):
        publisher_id = self.party_service.create_party(
            PartyPayload(
                legal_name="North Star Music Publishing B.V.",
                display_name="North Star Publishing",
                party_type="publisher",
            )
        )

        work_id = self.work_service.create_work(
            WorkPayload(
                title="North Star Anthem",
                contributors=[
                    WorkContributorPayload(
                        role="publisher",
                        name="North Star Publishing",
                        party_id=publisher_id,
                    )
                ],
            )
        )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 1)
        contributor_row = self.conn.execute(
            """
            SELECT party_id, display_name
            FROM WorkContributors
            WHERE work_id=?
            """,
            (work_id,),
        ).fetchone()
        assert contributor_row is not None
        self.assertEqual(contributor_row[0], publisher_id)
        self.assertEqual(contributor_row[1], "North Star Publishing")

    def test_work_validation_flags_invalid_split_totals_and_duplicate_iswc(self):
        self.work_service.create_work(
            WorkPayload(
                title="Existing Work",
                iswc="T-999.111.222-3",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Existing Writer",
                        share_percent=100,
                    )
                ],
            )
        )

        issues = self.work_service.validate_work(
            WorkPayload(
                title="Conflicting Work",
                iswc="T-999.111.222-3",
                contributors=[
                    WorkContributorPayload(role="songwriter", name="Writer A", share_percent=25),
                    WorkContributorPayload(role="composer", name="Writer B", share_percent=25),
                ],
            )
        )

        self.assertTrue(any(issue.field_name == "iswc" for issue in issues))
        self.assertTrue(any(issue.field_name == "share_percent" for issue in issues))

    def test_work_duplicate_update_listing_and_primary_track_reassignment(self):
        first_track_id = self._create_track("NL-ABC-26-00011", "Signal Song")
        second_track_id = self._create_track("NL-ABC-26-00012", "Signal Song Acoustic")
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Signal Song",
                iswc="T-444.555.666-7",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Signal Writer",
                        share_percent=100,
                    )
                ],
                track_ids=[first_track_id],
                work_status="idea",
            )
        )

        duplicate_id = self.work_service.duplicate_work(work_id)
        duplicate = self.work_service.fetch_work_detail(duplicate_id)
        assert duplicate is not None
        self.assertEqual(duplicate.work.title, "Signal Song (Copy)")
        self.assertIsNone(duplicate.work.iswc)

        self.work_service.update_work(
            work_id,
            WorkPayload(
                title="Signal Song",
                alternate_titles=["Signal Anthem"],
                version_subtitle="Radio Mix",
                iswc="T-444.555.666-7",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Signal Writer",
                        share_percent=50,
                        role_share_percent=50,
                    ),
                    WorkContributorPayload(
                        role="composer",
                        name="Signal Composer",
                        share_percent=50,
                        role_share_percent=50,
                    ),
                ],
                track_ids=[first_track_id, second_track_id],
                work_status="contract_pending",
            ),
        )

        listed = self.work_service.list_works(
            search_text="Signal Anthem",
            status="contract pending",
            linked_track_id=second_track_id,
        )
        self.assertEqual([item.id for item in listed], [work_id])

        self.work_service.unlink_track(work_id, first_track_id)
        remaining_links = self.conn.execute(
            """
            SELECT track_id, is_primary
            FROM WorkTrackLinks
            WHERE work_id=?
            ORDER BY track_id
            """,
            (work_id,),
        ).fetchall()
        self.assertEqual(remaining_links, [(second_track_id, 1)])
        self.assertIsNone(
            self.conn.execute(
                "SELECT work_id FROM Tracks WHERE id=?",
                (first_track_id,),
            ).fetchone()[0]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT work_id FROM Tracks WHERE id=?",
                (second_track_id,),
            ).fetchone()[0],
            work_id,
        )

        exported = self.work_service.export_rows()
        exported_work = next(row for row in exported if row["id"] == work_id)
        self.assertEqual(exported_work["track_ids"], [second_track_id])
        self.assertEqual(len(exported_work["contributors"]), 2)

    def test_creating_a_second_work_reassigns_track_governance_to_the_new_parent(self):
        track_id = self._create_track("NL-ABC-26-00021", "One Parent Only")
        first_work_id = self.work_service.create_work(
            WorkPayload(
                title="First Parent",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Primary Writer",
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )

        second_work_id = self.work_service.create_work(
            WorkPayload(
                title="Second Parent",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Replacement Writer",
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )

        self.assertEqual(
            self.conn.execute("SELECT work_id FROM Tracks WHERE id=?", (track_id,)).fetchone()[0],
            second_work_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT work_id, track_id, is_primary FROM WorkTrackLinks ORDER BY work_id, track_id"
            ).fetchall(),
            [(second_work_id, track_id, 1)],
        )
        self.assertEqual(self.work_service.fetch_work_detail(first_work_id).track_ids, [])
        self.assertEqual(self.work_service.fetch_work_detail(second_work_id).track_ids, [track_id])

    def test_party_duplicate_detection_merge_usage_summary_and_filters(self):
        primary_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Music BV",
                display_name="Signal Music",
                email="info@signal.test",
                ipi_cae="IPI-001",
            )
        )
        duplicate_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Music BV",
                email="other@signal.test",
            )
        )
        cursor = self.conn.execute(
            """
            INSERT INTO Parties (legal_name, email, ipi_cae, party_type)
            VALUES (?, ?, ?, ?)
            """,
            ("Signal Rights BV", "info@signal.test", "IPI-002", "organization"),
        )
        mirrored_email_id = int(cursor.lastrowid)
        reused_id = self.party_service.ensure_party_by_name("Signal Music")
        self.assertEqual(reused_id, primary_id)

        work_id = self.work_service.create_work(
            WorkPayload(
                title="Signal Song",
                contributors=[
                    WorkContributorPayload(
                        role="publisher",
                        name="Signal Music BV",
                        party_id=duplicate_id,
                    )
                ],
            )
        )
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Signal Deal",
                parties=[
                    ContractPartyPayload(party_id=duplicate_id, role_label="publisher"),
                ],
            )
        )
        right_id = self.rights_service.create_right(
            RightPayload(
                title="Signal Right",
                right_type="master",
                granted_to_party_id=duplicate_id,
                track_id=self._create_track("NL-ABC-26-00013", "Signal Rights"),
            )
        )
        self.rights_service.replace_work_ownership_interests(
            work_id,
            [
                OwnershipInterestPayload(
                    role="publisher",
                    party_id=duplicate_id,
                    name="Signal Music BV",
                    share_percent=100,
                )
            ],
        )
        self.rights_service.replace_recording_ownership_interests(
            self._create_track("NL-ABC-26-00014", "Signal Master Owner"),
            [
                OwnershipInterestPayload(
                    role="master_owner",
                    party_id=duplicate_id,
                    name="Signal Music BV",
                    share_percent=100,
                )
            ],
        )
        self.assertGreater(contract_id, 0)
        self.assertGreater(right_id, 0)

        duplicates = self.party_service.detect_duplicates()
        duplicate_types = {item.match_type for item in duplicates}
        self.assertIn("legal_name", duplicate_types)
        self.assertIn("email", duplicate_types)

        listed = self.party_service.list_parties(
            search_text="signal",
            party_type="organization",
        )
        self.assertTrue(any(item.id == primary_id for item in listed))

        usage_before_merge = self.party_service.usage_summary(duplicate_id)
        self.assertEqual(usage_before_merge.work_count, 1)
        self.assertEqual(usage_before_merge.contract_count, 1)
        self.assertEqual(usage_before_merge.rights_count, 1)

        merged = self.party_service.merge_parties(primary_id, [duplicate_id, mirrored_email_id])
        self.assertEqual(merged.id, primary_id)
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM WorkContributors WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM WorkContributionEntries WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM ContractParties WHERE contract_id=?",
                (contract_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT granted_to_party_id FROM RightsRecords WHERE id=?",
                (right_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT party_id FROM WorkOwnershipInterests WHERE work_id=?",
                (work_id,),
            ).fetchone()[0],
            primary_id,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM RecordingOwnershipInterests WHERE party_id=?",
                (primary_id,),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(merged.artist_aliases, ())

    def test_party_service_round_trips_expanded_fields_aliases_and_alias_lookup(self):
        party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Aeonium",
                artist_name="Aeonium Official",
                company_name="Aeonium Holdings",
                first_name="Lyra",
                middle_name="Van",
                last_name="Moonwake",
                party_type="licensee",
                contact_person="Lyra Moonwake",
                email="hello@moonium.test",
                alternative_email="legal@moonium.test",
                phone="+31 20 555 0101",
                website="https://moonium.test",
                street_name="Main Street",
                street_number="12A",
                address_line1="Suite 4",
                address_line2="Attn Legal",
                city="Amsterdam",
                region="Noord-Holland",
                postal_code="1012AB",
                country="NL",
                bank_account_number="NL91TEST0123456789",
                chamber_of_commerce_number="CoC-778899",
                tax_id="TAX-778899",
                vat_number="NL001122334B01",
                pro_affiliation="BUMA/STEMRA",
                pro_number="PRO-778899",
                ipi_cae="IPI-778899",
                notes="Primary counterparty profile.",
                profile_name="AeoniumProfile",
                artist_aliases=["Aeonium", "Lyra C."],
            )
        )

        record = self.party_service.fetch_party(party_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.artist_name, "Aeonium Official")
        self.assertEqual(record.company_name, "Aeonium Holdings")
        self.assertEqual(record.first_name, "Lyra")
        self.assertEqual(record.middle_name, "Van")
        self.assertEqual(record.last_name, "Moonwake")
        self.assertEqual(record.alternative_email, "legal@moonium.test")
        self.assertEqual(record.street_name, "Main Street")
        self.assertEqual(record.street_number, "12A")
        self.assertEqual(record.bank_account_number, "NL91TEST0123456789")
        self.assertEqual(record.chamber_of_commerce_number, "CoC-778899")
        self.assertEqual(record.pro_number, "PRO-778899")
        self.assertEqual(record.artist_aliases, ("Aeonium", "Lyra C."))

        alias_rows = self.party_service.list_artist_aliases(party_id)
        self.assertEqual([item.alias_name for item in alias_rows], ["Aeonium", "Lyra C."])
        self.assertEqual(self.party_service.find_party_id_by_name("Aeonium"), party_id)
        self.assertEqual(self.party_service.find_party_id_by_name("Lyra C."), party_id)
        self.assertEqual(self.party_service.ensure_party_by_name("Aeonium"), party_id)

        search_hits = self.party_service.list_parties(search_text="CoC-778899")
        self.assertEqual([item.id for item in search_hits], [party_id])
        search_hits = self.party_service.list_parties(search_text="Lyra C.")
        self.assertEqual([item.id for item in search_hits], [party_id])

        self.party_service.update_party(
            party_id,
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Aeonium Licensing",
                artist_name="Aeonium Official",
                company_name="Aeonium Holdings",
                first_name="Lyra",
                middle_name="Van",
                last_name="Moonwake",
                party_type="licensee",
                contact_person="Lyra Moonwake",
                email="hello@moonium.test",
                alternative_email="contracts@moonium.test",
                phone="+31 20 555 0101",
                website="https://moonium.test",
                street_name="Main Street",
                street_number="12A",
                address_line1="Suite 4",
                address_line2="Attn Legal",
                city="Amsterdam",
                region="Noord-Holland",
                postal_code="1012AB",
                country="NL",
                bank_account_number="NL91TEST0123456789",
                chamber_of_commerce_number="CoC-778899",
                tax_id="TAX-778899",
                vat_number="NL001122334B01",
                pro_affiliation="BUMA/STEMRA",
                pro_number="PRO-778899",
                ipi_cae="IPI-778899",
                notes="Updated counterparty profile.",
                profile_name="AeoniumProfile",
                artist_aliases=["Aeonium", "Lyra Cosmos"],
            ),
        )

        updated = self.party_service.fetch_party(party_id)
        assert updated is not None
        self.assertEqual(updated.display_name, "Aeonium Licensing")
        self.assertEqual(updated.alternative_email, "contracts@moonium.test")
        self.assertEqual(updated.artist_aliases, ("Aeonium", "Lyra Cosmos"))

        exported = self.party_service.export_rows()
        exported_row = next(row for row in exported if row["id"] == party_id)
        self.assertEqual(exported_row["artist_name"], "Aeonium Official")
        self.assertEqual(exported_row["company_name"], "Aeonium Holdings")
        self.assertEqual(exported_row["first_name"], "Lyra")
        self.assertEqual(exported_row["alternative_email"], "contracts@moonium.test")
        self.assertEqual(exported_row["chamber_of_commerce_number"], "CoC-778899")
        self.assertEqual(exported_row["pro_number"], "PRO-778899")
        self.assertEqual(exported_row["artist_aliases"], ("Aeonium", "Lyra Cosmos"))

    def test_party_merge_promotes_missing_artist_name_and_preserves_aliases(self):
        primary_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Holdings B.V.",
                display_name="Signal Holdings",
                party_type="organization",
                artist_aliases=["Signal Legacy"],
            )
        )
        duplicate_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Signal Artist Entity",
                artist_name="Signal Artist",
                party_type="artist",
                artist_aliases=["Signal Artist Duo"],
            )
        )

        merged = self.party_service.merge_parties(primary_id, [duplicate_id])

        self.assertEqual(merged.artist_name, "Signal Artist")
        self.assertEqual(
            merged.artist_aliases,
            ("Signal Legacy", "Signal Artist Duo"),
        )
        self.assertEqual(self.party_service.find_party_id_by_name("Signal Artist Duo"), primary_id)
        self.assertEqual(self.party_service.find_party_id_by_name("Signal Artist"), primary_id)


if __name__ == "__main__":
    unittest.main()

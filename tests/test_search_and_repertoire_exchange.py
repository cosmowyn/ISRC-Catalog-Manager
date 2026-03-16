import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class SearchAndRepertoireExchangeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)
        self.party_service = PartyService(self.conn)
        self.work_service = WorkService(self.conn, party_service=self.party_service)
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(self.conn)
        self.asset_service = AssetService(self.conn, self.data_root)
        self.search_service = GlobalSearchService(self.conn)
        self.relationship_service = RelationshipExplorerService(self.conn)
        self.exchange_service = RepertoireExchangeService(
            self.conn,
            party_service=self.party_service,
            work_service=self.work_service,
            contract_service=self.contract_service,
            rights_service=self.rights_service,
            asset_service=self.asset_service,
            data_root=self.data_root,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _seed_repertoire(self) -> dict[str, int]:
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00009",
                track_title="Midnight Circuit",
                artist_name="Nova",
                additional_artists=[],
                album_title="Night Runs",
                release_date="2026-03-16",
                track_length_sec=222,
                iswc="T-222.333.444-5",
                upc="036000291452",
                genre="Synth",
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Night Runs",
                primary_artist="Nova",
                release_type="single",
                release_date="2026-03-16",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id, disc_number=1, track_number=1, sequence_number=1
                    )
                ],
            )
        )
        party_id = self.party_service.create_party(PartyPayload(legal_name="Nova Music"))
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Midnight Circuit",
                iswc="T-222.333.444-5",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter", name="Nova Music", party_id=party_id, share_percent=100
                    )
                ],
                track_ids=[track_id],
            )
        )
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Nova Distribution Agreement",
                contract_type="distribution",
                status="active",
                parties=[
                    ContractPartyPayload(party_id=party_id, role_label="label", is_primary=True)
                ],
                work_ids=[work_id],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )
        right_id = self.rights_service.create_right(
            RightPayload(
                title="Master Distribution Right",
                right_type="master",
                exclusive_flag=True,
                territory="Worldwide",
                granted_to_party_id=party_id,
                source_contract_id=contract_id,
                work_id=work_id,
                track_id=track_id,
                release_id=release_id,
            )
        )
        asset_path = self.data_root / "midnight.wav"
        asset_path.write_bytes(b"RIFFdemo")
        asset_id = self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(asset_path),
                approved_for_use=True,
                primary_flag=True,
                track_id=track_id,
            )
        )
        return {
            "track_id": track_id,
            "release_id": release_id,
            "party_id": party_id,
            "work_id": work_id,
            "contract_id": contract_id,
            "right_id": right_id,
            "asset_id": asset_id,
        }

    def test_global_search_and_relationship_explorer(self):
        ids = self._seed_repertoire()

        results = self.search_service.search("Midnight")
        entity_types = {item.entity_type for item in results}
        self.assertIn("work", entity_types)
        self.assertIn("track", entity_types)

        sections = self.relationship_service.describe_links("track", ids["track_id"])
        section_titles = {section.section_title for section in sections}
        self.assertTrue({"Works", "Releases", "Contracts", "Rights", "Assets"} <= section_titles)

    def test_repertoire_exchange_json_round_trip(self):
        self._seed_repertoire()
        export_path = self.data_root / "repertoire.json"
        self.exchange_service.export_json(export_path)

        new_conn = sqlite3.connect(":memory:")
        new_conn.execute("PRAGMA foreign_keys = ON")
        try:
            schema = DatabaseSchemaService(new_conn, data_root=self.data_root)
            schema.init_db()
            schema.migrate_schema()
            track_service = TrackService(new_conn, self.data_root)
            release_service = ReleaseService(new_conn, self.data_root)
            imported_track_id = track_service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00009",
                    track_title="Midnight Circuit",
                    artist_name="Nova",
                    additional_artists=[],
                    album_title="Night Runs",
                    release_date="2026-03-16",
                    track_length_sec=222,
                    iswc="T-222.333.444-5",
                    upc="036000291452",
                    genre="Synth",
                )
            )
            release_service.create_release(
                ReleasePayload(
                    title="Night Runs",
                    primary_artist="Nova",
                    release_type="single",
                    release_date="2026-03-16",
                    upc="036000291452",
                    placements=[
                        ReleaseTrackPlacement(
                            track_id=imported_track_id,
                            disc_number=1,
                            track_number=1,
                            sequence_number=1,
                        )
                    ],
                )
            )
            party_service = PartyService(new_conn)
            work_service = WorkService(new_conn, party_service=party_service)
            contract_service = ContractService(
                new_conn, self.data_root, party_service=party_service
            )
            rights_service = RightsService(new_conn)
            asset_service = AssetService(new_conn, self.data_root)
            exchange_service = RepertoireExchangeService(
                new_conn,
                party_service=party_service,
                work_service=work_service,
                contract_service=contract_service,
                rights_service=rights_service,
                asset_service=asset_service,
                data_root=self.data_root,
            )

            exchange_service.import_json(export_path)

            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 1)
            self.assertEqual(
                new_conn.execute("SELECT COUNT(*) FROM RightsRecords").fetchone()[0], 1
            )
            self.assertEqual(
                new_conn.execute("SELECT COUNT(*) FROM AssetVersions").fetchone()[0], 1
            )
        finally:
            new_conn.close()


if __name__ == "__main__":
    unittest.main()

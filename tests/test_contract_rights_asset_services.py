import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService


class ContractRightsAssetServiceTests(unittest.TestCase):
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
        self.contract_service = ContractService(
            self.conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(self.conn)
        self.asset_service = AssetService(self.conn, self.data_root)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_track_and_release(self) -> tuple[int, int]:
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00003",
                track_title="Contract Song",
                artist_name="Contract Artist",
                additional_artists=[],
                album_title="Contract Album",
                release_date="2026-03-16",
                track_length_sec=200,
                iswc=None,
                upc="036000291452",
                genre="Pop",
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Contract Album",
                primary_artist="Contract Artist",
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
        return track_id, release_id

    def test_contract_deadlines_and_document_validation(self):
        party_id = self.party_service.create_party(PartyPayload(legal_name="North Label"))
        document_path = self.data_root / "agreement.txt"
        document_path.write_text("signed agreement", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="North Label License",
                contract_type="license",
                status="active",
                signature_date="2026-03-10",
                notice_deadline="2026-03-20",
                parties=[
                    ContractPartyPayload(party_id=party_id, role_label="licensee", is_primary=True)
                ],
                obligations=[
                    ContractObligationPayload(
                        obligation_type="delivery",
                        title="Deliver final WAV",
                        due_date="2026-03-25",
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        title="Signed Version",
                        document_type="signed_agreement",
                        source_path=str(document_path),
                        signed_by_all_parties=True,
                        active_flag=True,
                    ),
                    ContractDocumentPayload(
                        title="Amendment A",
                        document_type="amendment",
                    ),
                ],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(len(detail.documents), 2)
        self.assertTrue(any(doc.active_flag for doc in detail.documents))
        issues = self.contract_service.validate_contract(
            ContractPayload(
                title=detail.contract.title,
                status=detail.contract.status,
                signature_date=detail.contract.signature_date,
                notice_deadline=detail.contract.notice_deadline,
                parties=[
                    ContractPartyPayload(
                        party_id=item.party_id,
                        role_label=item.role_label,
                        is_primary=item.is_primary,
                    )
                    for item in detail.parties
                ],
                obligations=[
                    ContractObligationPayload(
                        obligation_type=item.obligation_type,
                        title=item.title,
                        due_date=item.due_date,
                    )
                    for item in detail.obligations
                ],
                documents=[
                    ContractDocumentPayload(
                        document_id=item.id,
                        title=item.title,
                        document_type=item.document_type,
                        active_flag=item.active_flag,
                        signed_by_all_parties=item.signed_by_all_parties,
                        supersedes_document_id=item.supersedes_document_id,
                    )
                    for item in detail.documents
                ],
            )
        )
        self.assertTrue(any("Amendment" in issue.message for issue in issues))

        deadlines = self.contract_service.upcoming_deadlines(within_days=20)
        self.assertTrue(any(item.contract_id == contract_id for item in deadlines))

    def test_rights_conflict_detection_and_missing_source_contract(self):
        granted_to = self.party_service.create_party(PartyPayload(legal_name="Sync House"))
        retained = self.party_service.create_party(PartyPayload(legal_name="Artist Control"))
        track_id, release_id = self._create_track_and_release()

        right_one = self.rights_service.create_right(
            RightPayload(
                title="EU Master License A",
                right_type="master",
                exclusive_flag=True,
                territory="EU",
                start_date="2026-01-01",
                end_date="2026-12-31",
                granted_to_party_id=granted_to,
                retained_by_party_id=retained,
                track_id=track_id,
                release_id=release_id,
            )
        )
        right_two = self.rights_service.create_right(
            RightPayload(
                title="EU Master License B",
                right_type="master",
                exclusive_flag=True,
                territory="EU",
                start_date="2026-06-01",
                end_date="2026-12-31",
                granted_to_party_id=granted_to,
                retained_by_party_id=retained,
                track_id=track_id,
            )
        )

        conflicts = self.rights_service.detect_conflicts()
        self.assertTrue(
            any(
                {conflict.left_right_id, conflict.right_right_id} == {right_one, right_two}
                for conflict in conflicts
            )
        )
        missing_source = self.rights_service.rights_missing_source_contract()
        self.assertTrue(any(item.id in {right_one, right_two} for item in missing_source))

    def test_asset_validation_catches_missing_approved_master(self):
        track_id, _release_id = self._create_track_and_release()
        master_path = self.data_root / "master.wav"
        master_path.write_bytes(b"RIFFdemo")

        asset_id = self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(master_path),
                approved_for_use=False,
                primary_flag=True,
                version_status="delivered",
                track_id=track_id,
            )
        )
        self.assertGreater(asset_id, 0)

        issues = self.asset_service.validate_assets()
        self.assertTrue(any(issue.issue_type == "missing_approved_master" for issue in issues))


if __name__ == "__main__":
    unittest.main()

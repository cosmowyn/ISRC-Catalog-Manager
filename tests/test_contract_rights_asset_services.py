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
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager.contracts.dialogs import ContractDocumentEditor
except Exception:  # pragma: no cover - environment-specific fallback
    ContractDocumentEditor = None


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
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        return track_id, release_id

    @staticmethod
    def _document_payload_from_record(record):
        return ContractDocumentPayload(
            document_id=record.id,
            title=record.title,
            document_type=record.document_type,
            version_label=record.version_label,
            created_date=record.created_date,
            received_date=record.received_date,
            signed_status=record.signed_status,
            signed_by_all_parties=record.signed_by_all_parties,
            active_flag=record.active_flag,
            supersedes_document_id=record.supersedes_document_id,
            superseded_by_document_id=record.superseded_by_document_id,
            stored_path=record.file_path,
            storage_mode=record.storage_mode,
            filename=record.filename,
            checksum_sha256=record.checksum_sha256,
            notes=record.notes,
        )

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

    def test_contract_update_search_export_and_delete_cleanup(self):
        track_id, release_id = self._create_track_and_release()
        original_path = self.data_root / "draft.txt"
        replacement_path = self.data_root / "final.txt"
        original_path.write_text("draft agreement", encoding="utf-8")
        replacement_path.write_text("final agreement", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="South Agency Agreement",
                contract_type="services",
                status="active",
                signature_date="2026-03-10",
                notice_deadline="2026-03-18",
                parties=[
                    ContractPartyPayload(name="South Agency", role_label="manager", is_primary=True)
                ],
                obligations=[
                    ContractObligationPayload(
                        obligation_type="follow_up",
                        title="Check approval notes",
                        due_date="2026-03-19",
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        title="Draft Version",
                        document_type="draft",
                        source_path=str(original_path),
                    )
                ],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        assert detail is not None
        self.assertEqual(detail.parties[0].party_name, "South Agency")
        original_stored_path = detail.documents[0].file_path
        original_resolved_path = self.contract_service.resolve_document_path(original_stored_path)
        assert original_resolved_path is not None
        self.assertTrue(original_resolved_path.exists())

        self.contract_service.update_contract(
            contract_id,
            ContractPayload(
                title="South Agency Agreement",
                contract_type="services",
                status="active",
                signature_date="2026-03-10",
                notice_deadline="2026-03-18",
                summary="Updated summary",
                parties=[
                    ContractPartyPayload(
                        party_id=detail.parties[0].party_id,
                        role_label="manager",
                        is_primary=True,
                    )
                ],
                obligations=[
                    ContractObligationPayload(
                        obligation_type="follow_up",
                        title="Check approval notes",
                        due_date="2026-03-19",
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        document_id=detail.documents[0].id,
                        title="Final Version",
                        document_type="signed_agreement",
                        source_path=str(replacement_path),
                        signed_by_all_parties=True,
                        active_flag=True,
                    )
                ],
                track_ids=[track_id],
                release_ids=[release_id],
            ),
        )

        updated = self.contract_service.fetch_contract_detail(contract_id)
        assert updated is not None
        updated_document = updated.documents[0]
        updated_path = self.contract_service.resolve_document_path(updated_document.file_path)
        assert updated_path is not None
        self.assertTrue(updated_path.exists())
        self.assertEqual(updated_path.read_text(encoding="utf-8"), "final agreement")
        self.assertFalse(original_resolved_path.exists())

        search_results = self.contract_service.list_contracts(
            search_text="South Agency",
            status="active",
        )
        self.assertEqual([item.id for item in search_results], [contract_id])

        csv_path = self.data_root / "deadlines.csv"
        self.contract_service.export_deadlines_csv(csv_path, within_days=20)
        exported_lines = csv_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(exported_lines[0], "contract_id,title,date_field,due_date")
        self.assertTrue(any("South Agency Agreement" in line for line in exported_lines[1:]))

    def test_contract_documents_support_managed_and_database_storage_modes(self):
        managed_path = self.data_root / "managed-doc.txt"
        database_path = self.data_root / "database-doc.txt"
        managed_path.write_text("managed version", encoding="utf-8")
        database_path.write_text("database version", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Storage Mode Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Managed Copy",
                        document_type="draft",
                        source_path=str(managed_path),
                        storage_mode="managed_file",
                    ),
                    ContractDocumentPayload(
                        title="Database Copy",
                        document_type="draft",
                        source_path=str(database_path),
                        storage_mode="database",
                    ),
                ],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        managed_doc = next(doc for doc in detail.documents if doc.title == "Managed Copy")
        database_doc = next(doc for doc in detail.documents if doc.title == "Database Copy")

        self.assertEqual(managed_doc.storage_mode, "managed_file")
        self.assertIsNotNone(managed_doc.file_path)
        self.assertTrue(self.contract_service.resolve_document_path(managed_doc.file_path).exists())
        self.assertEqual(database_doc.storage_mode, "database")
        self.assertIsNone(database_doc.file_path)

        converted_database = self.contract_service.convert_document_storage_mode(
            managed_doc.id, "database"
        )
        self.assertEqual(converted_database.storage_mode, "database")
        self.assertIsNone(converted_database.file_path)

        converted_managed = self.contract_service.convert_document_storage_mode(
            converted_database.id, "managed_file"
        )
        self.assertEqual(converted_managed.storage_mode, "managed_file")
        self.assertIsNotNone(converted_managed.file_path)
        converted_path = self.contract_service.resolve_document_path(converted_managed.file_path)
        self.assertTrue(converted_path.exists())

        self.contract_service.delete_contract(contract_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 0)
        self.assertFalse(converted_path.exists())

    def test_contract_document_update_preserves_storage_metadata_on_noop_save(self):
        document_path = self.data_root / "round-trip.docx"
        document_path.write_text("contract round trip", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Round Trip Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Round Trip Copy",
                        document_type="signed_agreement",
                        source_path=str(document_path),
                        storage_mode="managed_file",
                        signed_by_all_parties=True,
                        active_flag=True,
                    )
                ],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        original = detail.documents[0]
        payload = ContractPayload(
            title=detail.contract.title,
            status=detail.contract.status,
            documents=[
                self._document_payload_from_record(original),
            ],
        )
        self.contract_service.update_contract(contract_id, payload)

        updated = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        refreshed = updated.documents[0]
        self.assertEqual(refreshed.file_path, original.file_path)
        self.assertEqual(refreshed.filename, original.filename)
        self.assertEqual(refreshed.checksum_sha256, original.checksum_sha256)
        self.assertEqual(refreshed.storage_mode, original.storage_mode)
        self.assertEqual(refreshed.supersedes_document_id, original.supersedes_document_id)
        self.assertEqual(refreshed.superseded_by_document_id, original.superseded_by_document_id)

    def test_contract_document_storage_mode_round_trip_via_update(self):
        document_path = self.data_root / "mode-switch.txt"
        document_path.write_text("managed bytes", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Mode Switch Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Mode Switch Copy",
                        document_type="draft",
                        source_path=str(document_path),
                        storage_mode="managed_file",
                    )
                ],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        original = detail.documents[0]
        managed_bytes = document_path.read_bytes()

        self.contract_service.update_contract(
            contract_id,
            ContractPayload(
                title=detail.contract.title,
                status=detail.contract.status,
                documents=[
                    ContractDocumentPayload(
                        document_id=original.id,
                        title=original.title,
                        document_type=original.document_type,
                        version_label=original.version_label,
                        created_date=original.created_date,
                        received_date=original.received_date,
                        signed_status=original.signed_status,
                        signed_by_all_parties=original.signed_by_all_parties,
                        active_flag=original.active_flag,
                        supersedes_document_id=original.supersedes_document_id,
                        superseded_by_document_id=original.superseded_by_document_id,
                        stored_path=original.file_path,
                        storage_mode="database",
                        filename=original.filename,
                        checksum_sha256=original.checksum_sha256,
                        notes=original.notes,
                    )
                ],
            ),
        )
        converted = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(converted)
        assert converted is not None
        database_doc = converted.documents[0]
        self.assertEqual(database_doc.storage_mode, "database")
        self.assertIsNone(database_doc.file_path)
        db_bytes, _ = self.contract_service.fetch_document_bytes(database_doc.id)
        self.assertEqual(db_bytes, managed_bytes)

        self.contract_service.update_contract(
            contract_id,
            ContractPayload(
                title=detail.contract.title,
                status=detail.contract.status,
                documents=[
                    ContractDocumentPayload(
                        document_id=database_doc.id,
                        title=database_doc.title,
                        document_type=database_doc.document_type,
                        version_label=database_doc.version_label,
                        created_date=database_doc.created_date,
                        received_date=database_doc.received_date,
                        signed_status=database_doc.signed_status,
                        signed_by_all_parties=database_doc.signed_by_all_parties,
                        active_flag=database_doc.active_flag,
                        supersedes_document_id=database_doc.supersedes_document_id,
                        superseded_by_document_id=database_doc.superseded_by_document_id,
                        storage_mode="managed_file",
                        filename=database_doc.filename,
                        checksum_sha256=database_doc.checksum_sha256,
                        notes=database_doc.notes,
                    )
                ],
            ),
        )
        restored = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(restored)
        assert restored is not None
        restored_doc = restored.documents[0]
        self.assertEqual(restored_doc.storage_mode, "managed_file")
        self.assertIsNotNone(restored_doc.file_path)
        restored_path = self.contract_service.resolve_document_path(restored_doc.file_path)
        self.assertIsNotNone(restored_path)
        assert restored_path is not None
        self.assertTrue(restored_path.exists())
        self.assertEqual(restored_path.read_bytes(), managed_bytes)

    def test_contract_document_editor_open_and_export_helpers(self):
        if ContractDocumentEditor is None:
            self.skipTest("Contract document editor unavailable")
        require_qapplication()

        managed_path = self.data_root / "open-managed.txt"
        database_path = self.data_root / "open-database.txt"
        managed_path.write_text("managed open", encoding="utf-8")
        database_path.write_text("database open", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Open Helper Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Managed Helper",
                        document_type="draft",
                        source_path=str(managed_path),
                        storage_mode="managed_file",
                    ),
                    ContractDocumentPayload(
                        title="Database Helper",
                        document_type="draft",
                        source_path=str(database_path),
                        storage_mode="database",
                    ),
                ],
            )
        )

        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        editor = ContractDocumentEditor(contract_service=self.contract_service)
        try:
            editor.load_documents(detail.documents)

            for row in range(editor.documents_table.rowCount()):
                editor.documents_table.selectRow(row)
                editor._load_document_into_form(row)
                document = editor._current_document()[1]
                assert document is not None
                preview_path = editor._materialize_document(document)
                self.assertTrue(preview_path.exists())
                self.assertEqual(preview_path.read_bytes(), self.contract_service.fetch_document_bytes(document.document_id)[0])

                export_path = self.data_root / f"exported-{row}.bin"
                written = editor._export_selected_document(export_path)
                self.assertEqual(written, export_path)
                self.assertTrue(export_path.exists())
                self.assertEqual(export_path.read_bytes(), preview_path.read_bytes())
        finally:
            editor.close()

    def test_contract_validation_rejects_invalid_date_ranges(self):
        with self.assertRaises(ValueError):
            self.contract_service.create_contract(
                ContractPayload(
                    title="Broken Contract",
                    start_date="2026-03-20",
                    end_date="2026-03-10",
                )
            )

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

    def test_rights_filters_summary_update_and_delete(self):
        granted_to = self.party_service.create_party(PartyPayload(legal_name="Master Label"))
        retained = self.party_service.create_party(PartyPayload(legal_name="Writer Control"))
        track_id, release_id = self._create_track_and_release()
        contract_id = self.contract_service.create_contract(
            ContractPayload(title="Rights Contract", status="draft")
        )

        master_id = self.rights_service.create_right(
            RightPayload(
                title="Master Right",
                right_type="master",
                exclusive_flag=True,
                territory="Worldwide",
                granted_to_party_id=granted_to,
                source_contract_id=contract_id,
                track_id=track_id,
                release_id=release_id,
            )
        )
        publishing_id = self.rights_service.create_right(
            RightPayload(
                title="Publishing Right",
                right_type="composition_publishing",
                territory="Benelux",
                granted_to_party_id=granted_to,
                retained_by_party_id=retained,
                track_id=track_id,
            )
        )
        promo_id = self.rights_service.create_right(
            RightPayload(
                title="Promo Use",
                right_type="promotional",
                granted_to_party_id=granted_to,
                track_id=track_id,
            )
        )

        filtered = self.rights_service.list_rights(
            search_text="Worldwide", entity_type="track", entity_id=track_id
        )
        self.assertEqual([item.id for item in filtered], [master_id])

        summary = self.rights_service.ownership_summary(entity_type="track", entity_id=track_id)
        self.assertEqual(summary.master_control, ["Master Label"])
        self.assertEqual(summary.publishing_control, ["Master Label"])
        self.assertIn("Worldwide: Master Label", summary.exclusive_territories)

        self.rights_service.update_right(
            publishing_id,
            RightPayload(
                title="Publishing Right",
                right_type="composition_publishing",
                territory="Worldwide",
                granted_to_party_id=granted_to,
                retained_by_party_id=retained,
                track_id=track_id,
            ),
        )
        updated = self.rights_service.fetch_right(publishing_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.territory, "Worldwide")

        missing_source_ids = {
            item.id for item in self.rights_service.rights_missing_source_contract()
        }
        self.assertIn(publishing_id, missing_source_ids)
        self.assertNotIn(master_id, missing_source_ids)
        self.assertNotIn(promo_id, missing_source_ids)

        self.rights_service.delete_right(promo_id)
        self.assertIsNone(self.rights_service.fetch_right(promo_id))

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

    def test_asset_can_round_trip_between_database_and_managed_file_modes(self):
        track_id, release_id = self._create_track_and_release()
        master_path = self.data_root / "db-master.wav"
        master_path.write_bytes(b"RIFFdatabase")

        asset_id = self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(master_path),
                storage_mode="database",
                approved_for_use=True,
                primary_flag=True,
                version_status="delivered",
                track_id=track_id,
                release_id=release_id,
            )
        )

        asset = self.asset_service.fetch_asset(asset_id)
        assert asset is not None
        self.assertEqual(asset.storage_mode, "database")
        data, _ = self.asset_service.fetch_asset_bytes(asset_id)
        self.assertEqual(data, b"RIFFdatabase")

        converted = self.asset_service.convert_asset_storage_mode(asset_id, "managed_file")

        self.assertEqual(converted.storage_mode, "managed_file")
        self.assertTrue(converted.stored_path)
        self.assertTrue(self.asset_service.resolve_asset_path(converted.stored_path).exists())
        self.assertEqual(
            self.asset_service.resolve_asset_path(converted.stored_path).read_bytes(),
            b"RIFFdatabase",
        )

    def test_asset_update_listing_validation_and_delete_cleanup(self):
        track_id, release_id = self._create_track_and_release()
        master_path = self.data_root / "master.wav"
        alt_path = self.data_root / "radio-edit.wav"
        master_path.write_bytes(b"RIFFmaster")
        alt_path.write_bytes(b"RIFFradio")

        master_id = self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(master_path),
                approved_for_use=True,
                primary_flag=True,
                version_status="delivered",
                track_id=track_id,
                release_id=release_id,
            )
        )
        alt_id = self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="radio_edit",
                source_path=str(alt_path),
                approved_for_use=False,
                primary_flag=False,
                version_status="draft",
                track_id=track_id,
            )
        )

        self.asset_service.mark_primary(alt_id)
        master_record = self.asset_service.fetch_asset(master_id)
        alt_record = self.asset_service.fetch_asset(alt_id)
        assert master_record is not None
        assert alt_record is not None
        self.assertFalse(master_record.primary_flag)
        self.assertTrue(alt_record.primary_flag)

        replacement_path = self.data_root / "radio-edit-final.wav"
        replacement_path.write_bytes(b"RIFFupdated")
        self.asset_service.update_asset(
            alt_id,
            AssetVersionPayload(
                asset_type="radio_edit",
                source_path=str(replacement_path),
                approved_for_use=True,
                primary_flag=True,
                version_status="approved",
                track_id=track_id,
            ),
        )
        updated = self.asset_service.fetch_asset(alt_id)
        assert updated is not None
        self.assertEqual(updated.version_status, "approved")
        listed = self.asset_service.list_assets(track_id=track_id, search_text="radio")
        self.assertEqual([item.id for item in listed], [alt_id])

        self.conn.execute("UPDATE AssetVersions SET primary_flag=1 WHERE id=?", (master_id,))
        missing_file_path = self.asset_service.resolve_asset_path(updated.stored_path)
        assert missing_file_path is not None
        missing_file_path.unlink()
        issues = self.asset_service.validate_assets()
        issue_types = {issue.issue_type for issue in issues}
        self.assertIn("duplicate_primary_asset", issue_types)
        self.assertIn("broken_asset_reference", issue_types)

        self.asset_service.delete_asset(alt_id)
        self.assertIsNone(self.asset_service.fetch_asset(alt_id))


if __name__ == "__main__":
    unittest.main()

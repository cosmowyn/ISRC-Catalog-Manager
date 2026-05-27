from unittest import mock

from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    CATALOG_MODE_EMPTY,
    CATALOG_MODE_EXTERNAL,
    CATALOG_MODE_INTERNAL,
)
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class ContractServiceTests(ContractRightsAssetServiceTestCase):
    test_contract_deadlines_and_document_validation = (
        ContractRightsAssetServiceTestCase.case_contract_deadlines_and_document_validation
    )
    test_contract_update_search_export_and_delete_cleanup = (
        ContractRightsAssetServiceTestCase.case_contract_update_search_export_and_delete_cleanup
    )
    test_contract_documents_support_managed_and_database_storage_modes = (
        ContractRightsAssetServiceTestCase.case_contract_documents_support_managed_and_database_storage_modes
    )
    test_contract_document_update_preserves_storage_metadata_on_noop_save = (
        ContractRightsAssetServiceTestCase.case_contract_document_update_preserves_storage_metadata_on_noop_save
    )
    test_contract_document_editor_resolves_directory_selection_to_suggested_filename = (
        ContractRightsAssetServiceTestCase.case_contract_document_editor_resolves_directory_selection_to_suggested_filename
    )
    test_contract_document_storage_mode_round_trip_via_update = (
        ContractRightsAssetServiceTestCase.case_contract_document_storage_mode_round_trip_via_update
    )
    test_contract_validation_rejects_invalid_date_ranges = (
        ContractRightsAssetServiceTestCase.case_contract_validation_rejects_invalid_date_ranges
    )

    def test_contract_validation_covers_identifier_document_and_cleaning_edges(self):
        self.assertEqual(ContractService._clean_status("not a status"), "draft")
        self.assertEqual(ContractService._clean_obligation_type("not a type"), "other")
        self.assertEqual(ContractService._clean_document_type("not a type"), "other")
        self.assertEqual(
            ContractService._resolve_identifier_mode(
                mode=CATALOG_MODE_EXTERNAL,
                registry_entry_id=None,
                external_identifier_id=None,
                value=None,
            ),
            CATALOG_MODE_EXTERNAL,
        )
        self.assertEqual(
            ContractService._resolve_identifier_mode(
                mode=None,
                registry_entry_id=1,
                external_identifier_id=None,
                value=None,
            ),
            CATALOG_MODE_INTERNAL,
        )
        self.assertEqual(
            ContractService._resolve_identifier_mode(
                mode=None,
                registry_entry_id=None,
                external_identifier_id=2,
                value=None,
            ),
            CATALOG_MODE_EXTERNAL,
        )
        self.assertEqual(
            ContractService._resolve_identifier_mode(
                mode=None,
                registry_entry_id=None,
                external_identifier_id=None,
                value="MANUAL-1",
            ),
            "",
        )
        self.assertEqual(
            ContractService._resolve_identifier_mode(
                mode=None,
                registry_entry_id=None,
                external_identifier_id=None,
                value="",
            ),
            CATALOG_MODE_EMPTY,
        )
        with self.assertRaisesRegex(ValueError, "Unsupported contract registry category"):
            ContractService._contract_identifier_spec("unknown")

        payload = ContractPayload(
            title="Identifier Review Contract",
            status="active",
            contract_number_mode=CATALOG_MODE_INTERNAL,
            contract_registry_entry_id=1,
            contract_external_code_identifier_id=2,
            license_number_mode=CATALOG_MODE_INTERNAL,
            documents=[
                ContractDocumentPayload(
                    title="Signed A",
                    document_type="signed_agreement",
                    signed_by_all_parties=True,
                    active_flag=True,
                ),
                ContractDocumentPayload(
                    title="Signed B",
                    document_type="signed_agreement",
                    signed_by_all_parties=True,
                    active_flag=True,
                ),
                ContractDocumentPayload(title="Amendment", document_type="amendment"),
            ],
        )

        issues = self.contract_service.validate_contract(payload)
        messages = "\n".join(issue.message for issue in issues)

        self.assertIn("cannot carry both an internal registry link", messages)
        self.assertIn("Internal Registry but no value is selected", messages)
        self.assertIn("multiple active signed-agreement", messages)
        self.assertIn("does not declare which version", messages)

    def test_contract_document_storage_missing_and_unconfigured_edges(self):
        with self.assertRaises(FileNotFoundError):
            self.contract_service.fetch_document_bytes(999)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.contract_service.convert_document_storage_mode(999, "database")
        self.assertIsNone(self.contract_service._document_current_storage_mode(999))

        with self.assertRaisesRegex(FileNotFoundError, "No document blob"):
            self.contract_service._build_document_storage_payload(
                source_path=None,
                stored_path=None,
                filename="missing.pdf",
                checksum_sha256=None,
                storage_mode="database",
                existing_file_blob=None,
            )
        with self.assertRaisesRegex(FileNotFoundError, "No managed document path"):
            self.contract_service._build_document_storage_payload(
                source_path=None,
                stored_path=None,
                filename="missing.pdf",
                checksum_sha256=None,
                storage_mode="managed_file",
                existing_file_blob=None,
            )

        document_path = self.data_root / "database-only.txt"
        document_path.write_text("database document", encoding="utf-8")
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Database Document Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Database Copy",
                        document_type="draft",
                        source_path=str(document_path),
                        storage_mode="database",
                    )
                ],
            )
        )
        detail = self.contract_service.fetch_contract_detail(contract_id)
        assert detail is not None
        document_id = detail.documents[0].id

        unconfigured_service = ContractService(self.conn, None, party_service=self.party_service)
        with self.assertRaisesRegex(ValueError, "storage is not configured"):
            unconfigured_service.convert_document_storage_mode(document_id, "managed_file")

    def test_contract_private_replacers_skip_missing_input_and_deduplicate_associations(self):
        track_id, release_id = self._create_track_and_release()
        party_id = self.party_service.ensure_party_by_name("Counterparty")
        contract_id = self.contract_service.create_contract(
            ContractPayload(title="Replacement Target")
        )

        with self.conn:
            cursor = self.conn.cursor()
            self.contract_service._replace_parties(
                contract_id,
                [
                    ContractPartyPayload(name=""),
                    ContractPartyPayload(party_id=party_id, role_label="", is_primary=True),
                ],
                cursor=cursor,
            )
            self.contract_service._replace_obligations(
                contract_id,
                [
                    ContractObligationPayload(title=""),
                    ContractObligationPayload(title="Approve artwork", obligation_type="bad type"),
                ],
                cursor=cursor,
            )
            self.contract_service._replace_links(
                contract_id,
                "ContractTrackLinks",
                "track_id",
                [track_id, track_id, "bad", 0, -1],
                cursor=cursor,
            )
            self.contract_service._replace_links(
                contract_id,
                "ContractReleaseLinks",
                "release_id",
                [release_id, release_id, None],
                cursor=cursor,
            )

        self.assertEqual(
            self.conn.execute(
                "SELECT party_id, role_label, is_primary FROM ContractParties WHERE contract_id=?",
                (contract_id,),
            ).fetchall(),
            [(party_id, "counterparty", 1)],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT obligation_type, title FROM ContractObligations WHERE contract_id=?",
                (contract_id,),
            ).fetchall(),
            [("other", "Approve artwork")],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT track_id FROM ContractTrackLinks WHERE contract_id=?",
                (contract_id,),
            ).fetchall(),
            [(track_id,)],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT release_id FROM ContractReleaseLinks WHERE contract_id=?",
                (contract_id,),
            ).fetchall(),
            [(release_id,)],
        )

    def test_contract_document_cleanup_helpers_and_mode_detection(self):
        first_path = self.data_root / "contract_a.txt"
        first_path.write_text("primary agreement", encoding="utf-8")
        second_path = self.data_root / "contract_b.txt"
        second_path.write_text("secondary agreement", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Cleanup Contract",
                documents=[
                    ContractDocumentPayload(title="Managed A", source_path=str(first_path)),
                    ContractDocumentPayload(title="Managed B", source_path=str(second_path)),
                ],
            )
        )
        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        first_doc = detail.documents[0]
        self.assertEqual(
            self.contract_service._document_current_storage_mode(first_doc.id),
            "managed_file",
        )
        self.assertIsNone(self.contract_service._document_current_storage_mode(99_999))

        first_full = self.contract_service.resolve_document_path(first_doc.file_path)
        self.assertIsNotNone(first_full)
        orphan_path = self.contract_service.document_store.write_bytes(
            b"orphan document",
            filename="orphan.txt",
            subdir=None,
        )
        orphan_full = self.contract_service.resolve_document_path(orphan_path)
        self.assertIsNotNone(orphan_full)
        self.assertTrue(orphan_full.exists())

        with self.conn:
            cur = self.conn.cursor()
            self.contract_service._delete_document_if_unreferenced(None, cursor=cur)
            outside_path = self.data_root / "outside-document.txt"
            outside_path.write_text("outside", encoding="utf-8")
            self.contract_service._delete_document_if_unreferenced(str(outside_path), cursor=cur)
            self.contract_service._delete_document_if_unreferenced(first_doc.file_path, cursor=cur)
            self.contract_service._delete_document_if_unreferenced(orphan_path, cursor=cur)

        self.assertTrue(first_full.exists())
        self.assertFalse(orphan_full.exists())

    def test_contract_replace_documents_converts_managed_to_database_and_removes_stale_files(self):
        first_path = self.data_root / "contract_keep.txt"
        first_path.write_text("keep", encoding="utf-8")
        stale_path = self.data_root / "contract_stale.txt"
        stale_path.write_text("stale", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Replace Contract",
                documents=[
                    ContractDocumentPayload(title="Keep This", source_path=str(first_path)),
                    ContractDocumentPayload(title="Remove This", source_path=str(stale_path)),
                ],
            )
        )
        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        keep_doc = detail.documents[0]
        stale_doc = detail.documents[1]
        stale_full = self.contract_service.resolve_document_path(stale_doc.file_path)
        self.assertIsNotNone(stale_full)

        self.contract_service.update_contract(
            contract_id,
            ContractPayload(
                title="Replace Contract",
                documents=[
                    ContractDocumentPayload(
                        document_id=keep_doc.id,
                        title=keep_doc.title,
                        storage_mode="database",
                    )
                ],
            ),
        )

        updated = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(len(updated.documents), 1)
        self.assertEqual(updated.documents[0].storage_mode, "database")
        self.assertIsNone(updated.documents[0].file_path)
        self.assertFalse(stale_full.exists())

    def test_contract_replace_documents_converts_database_to_managed_file(self):
        source_path = self.data_root / "contract_db.txt"
        source_path.write_text("database source", encoding="utf-8")

        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Database Contract",
                documents=[
                    ContractDocumentPayload(
                        title="Stored DB",
                        source_path=str(source_path),
                        storage_mode="database",
                    )
                ],
            )
        )
        detail = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        doc = detail.documents[0]
        self.assertEqual(doc.storage_mode, "database")

        self.contract_service.update_contract(
            contract_id,
            ContractPayload(
                title="Database Contract",
                documents=[
                    ContractDocumentPayload(
                        document_id=doc.id,
                        title=doc.title,
                        storage_mode="managed_file",
                    )
                ],
            ),
        )

        updated = self.contract_service.fetch_contract_detail(contract_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        updated_doc = updated.documents[0]
        self.assertEqual(updated_doc.storage_mode, "managed_file")
        self.assertIsNotNone(updated_doc.file_path)
        self.assertIsNotNone(self.contract_service.resolve_document_path(updated_doc.file_path))
        self.assertEqual(
            self.contract_service._document_current_storage_mode(updated_doc.id),
            "managed_file",
        )

        bytes_payload, _ = self.contract_service.fetch_document_bytes(updated_doc.id)
        self.assertEqual(bytes_payload, b"database source")

    def test_contract_fetch_document_bytes_raises_for_missing_payloads(self):
        managed_path = self.data_root / "contract_fetch.txt"
        managed_path.write_text("managed content", encoding="utf-8")

        managed_contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Missing managed payload",
                documents=[
                    ContractDocumentPayload(
                        title="Managed Fetch",
                        source_path=str(managed_path),
                    )
                ],
            )
        )
        managed_detail = self.contract_service.fetch_contract_detail(managed_contract_id)
        self.assertIsNotNone(managed_detail)
        assert managed_detail is not None
        managed_doc = managed_detail.documents[0]
        resolved_managed = self.contract_service.resolve_document_path(managed_doc.file_path)
        self.assertIsNotNone(resolved_managed)
        resolved_managed.unlink()
        with self.assertRaises(FileNotFoundError):
            self.contract_service.fetch_document_bytes(managed_doc.id)

        db_path = self.data_root / "contract_fetch_db.txt"
        db_path.write_text("db content", encoding="utf-8")
        db_contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Missing blob payload",
                documents=[
                    ContractDocumentPayload(
                        title="Database Fetch",
                        source_path=str(db_path),
                        storage_mode="database",
                    )
                ],
            )
        )
        db_detail = self.contract_service.fetch_contract_detail(db_contract_id)
        self.assertIsNotNone(db_detail)
        assert db_detail is not None
        db_doc = db_detail.documents[0]
        with self.conn:
            self.conn.execute(
                "UPDATE ContractDocuments SET file_blob=NULL WHERE id=?",
                (db_doc.id,),
            )
        with self.assertRaises(FileNotFoundError):
            self.contract_service.fetch_document_bytes(db_doc.id)

    def test_contract_resolve_party_id_and_convert_requires_available_source(self):
        orphan_service = ContractService(self.conn, self.data_root, party_service=None)
        self.assertIsNone(
            orphan_service._resolve_party_id(
                ContractPartyPayload(name=""),
                cursor=self.conn.cursor(),
            )
        )
        self.assertIsNone(
            orphan_service._resolve_party_id(
                ContractPartyPayload(name="Missing"),
                cursor=self.conn.cursor(),
            )
        )

        base_path = self.data_root / "contract_convert.txt"
        base_path.write_text("source", encoding="utf-8")
        convert_id = self.contract_service.create_contract(
            ContractPayload(
                title="Missing source contract",
                documents=[
                    ContractDocumentPayload(
                        title="Managed to DB",
                        source_path=str(base_path),
                    )
                ],
            )
        )
        detail = self.contract_service.fetch_contract_detail(convert_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        doc = detail.documents[0]
        missing = self.data_root / "missing-convert-source.txt"
        with self.conn:
            self.conn.execute(
                "UPDATE ContractDocuments SET file_path=?, storage_mode='managed_file' WHERE id=?",
                (str(missing), doc.id),
            )
        with self.assertRaises(FileNotFoundError):
            self.contract_service.convert_document_storage_mode(doc.id, "database")

    def test_contract_registry_service_absence_and_identifier_sql_fallbacks(self):
        self.assertEqual(
            self.contract_service._contract_identifier_select_sql(BUILTIN_CATEGORY_CONTRACT_NUMBER),
            "c.contract_external_code_identifier_id",
        )

        contract_id = self.contract_service.create_contract(ContractPayload(title="Manual Only"))
        with mock.patch.object(
            self.contract_service,
            "_code_registry_service",
            return_value=None,
        ):
            self.assertIsNone(self.contract_service.code_registry_service())
            with self.assertRaisesRegex(ValueError, "Code registry service is unavailable"):
                self.contract_service.ensure_registry_value_for_contract(
                    contract_id,
                    system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                )
            with self.assertRaisesRegex(ValueError, "Code registry service is unavailable"):
                self.contract_service.generate_registry_value_for_contract(
                    contract_id,
                    system_key=BUILTIN_CATEGORY_CONTRACT_NUMBER,
                )


del ContractRightsAssetServiceTestCase

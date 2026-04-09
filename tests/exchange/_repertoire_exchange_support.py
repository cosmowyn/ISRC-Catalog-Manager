import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class SearchAndRepertoireExchangeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        services = self._build_services(self.conn, self.data_root)
        self.track_service = services["track_service"]
        self.release_service = services["release_service"]
        self.party_service = services["party_service"]
        self.work_service = services["work_service"]
        self.contract_service = services["contract_service"]
        self.rights_service = services["rights_service"]
        self.asset_service = services["asset_service"]
        self.search_service = services["search_service"]
        self.relationship_service = services["relationship_service"]
        self.exchange_service = services["exchange_service"]

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _build_services(self, conn: sqlite3.Connection, data_root: Path) -> dict[str, object]:
        schema = DatabaseSchemaService(conn, data_root=data_root)
        schema.init_db()
        schema.migrate_schema()
        track_service = TrackService(conn, data_root)
        release_service = ReleaseService(conn, data_root)
        party_service = PartyService(conn)
        work_service = WorkService(conn, party_service=party_service)
        contract_service = ContractService(conn, data_root, party_service=party_service)
        rights_service = RightsService(conn)
        asset_service = AssetService(conn, data_root)
        return {
            "track_service": track_service,
            "release_service": release_service,
            "party_service": party_service,
            "work_service": work_service,
            "contract_service": contract_service,
            "rights_service": rights_service,
            "asset_service": asset_service,
            "search_service": GlobalSearchService(conn),
            "relationship_service": RelationshipExplorerService(conn),
            "exchange_service": RepertoireExchangeService(
                conn,
                party_service=party_service,
                work_service=work_service,
                contract_service=contract_service,
                rights_service=rights_service,
                asset_service=asset_service,
                data_root=data_root,
            ),
        }

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
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        label_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Nova Music",
                display_name="Nova",
                artist_name="Nova Official",
                company_name="Nova Music Group",
                first_name="Nova",
                last_name="Artist",
                email="hello@nova.test",
                alternative_email="legal@nova.test",
                street_name="Canal Street",
                street_number="24",
                city="Amsterdam",
                postal_code="1017AA",
                country="NL",
                chamber_of_commerce_number="CoC-990011",
                pro_number="PRO-990011",
                artist_aliases=["Nova Alias", "Nova Stage Name"],
            )
        )
        control_party_id = self.party_service.create_party(PartyPayload(legal_name="Nova Holdings"))
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Midnight Circuit",
                iswc="T-222.333.444-5",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Nova Music",
                        party_id=label_party_id,
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )
        document_path = self.data_root / "distribution-agreement.txt"
        document_path.write_text("signed distribution agreement", encoding="utf-8")
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Nova Distribution Agreement",
                contract_type="distribution",
                status="active",
                parties=[
                    ContractPartyPayload(
                        party_id=label_party_id,
                        role_label="label",
                        is_primary=True,
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        title="Signed Agreement",
                        document_type="signed_agreement",
                        source_path=str(document_path),
                        signed_by_all_parties=True,
                        active_flag=True,
                    )
                ],
                work_ids=[work_id],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )
        detail = self.contract_service.fetch_contract_detail(contract_id)
        assert detail is not None
        document_id = detail.documents[0].id
        right_id = self.rights_service.create_right(
            RightPayload(
                title="Master Distribution Right",
                right_type="master",
                exclusive_flag=True,
                territory="Worldwide",
                granted_to_party_id=label_party_id,
                retained_by_party_id=control_party_id,
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
                release_id=release_id,
            )
        )
        return {
            "track_id": track_id,
            "release_id": release_id,
            "label_party_id": label_party_id,
            "control_party_id": control_party_id,
            "work_id": work_id,
            "contract_id": contract_id,
            "document_id": document_id,
            "right_id": right_id,
            "asset_id": asset_id,
        }

    def _prepare_import_target(
        self, data_root: Path
    ) -> tuple[sqlite3.Connection, dict[str, object], int, int]:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        services = self._build_services(conn, data_root)
        imported_track_id = services["track_service"].create_track(
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
        imported_release_id = services["release_service"].create_release(
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
        return conn, services, imported_track_id, imported_release_id

    def case_global_search_filters_saved_searches_and_relationship_explorer(self):
        ids = self._seed_repertoire()

        self.assertEqual(self.search_service.search("   "), [])
        filtered_results = self.search_service.search("Master", entity_types=["right"])
        self.assertEqual([item.entity_type for item in filtered_results], ["right"])

        search_results = self.search_service.search("Midnight")
        entity_types = {item.entity_type for item in search_results}
        self.assertTrue({"work", "track"} <= entity_types)

        for suffix in range(3):
            self.track_service.create_track(
                TrackCreatePayload(
                    isrc=f"NL-ABC-26-1{suffix:04d}",
                    track_title=f"Preview Track {suffix + 1}",
                    artist_name="Nova",
                    additional_artists=[],
                    album_title="Night Runs",
                    release_date="2026-03-16",
                    track_length_sec=180 + suffix,
                    iswc=None,
                    upc=None,
                    genre="Synth",
                )
            )
        overview_results = self.search_service.browse_default_view(limit=200, preview_limit=2)
        self.assertGreater(len(overview_results), 0)
        overview_entity_types = {item.entity_type for item in overview_results}
        self.assertTrue({"work", "track", "release"} <= overview_entity_types)
        track_preview = self.search_service.browse_default_view(
            entity_types=["track"], limit=200, preview_limit=2
        )
        self.assertTrue(all(item.entity_type == "track" for item in track_preview))
        self.assertLessEqual(len(track_preview), 2)

        saved_id = self.search_service.save_search("Midnight Works", "Midnight", ["work", "track"])
        updated_id = self.search_service.save_search("Midnight Works", "Nova", ["party"])
        self.assertEqual(saved_id, updated_id)
        saved_searches = self.search_service.list_saved_searches()
        self.assertEqual(
            [(item.name, item.query_text, item.entity_types) for item in saved_searches],
            [("Midnight Works", "Nova", ["party"])],
        )
        self.search_service.delete_saved_search(saved_id)
        self.assertEqual(self.search_service.list_saved_searches(), [])

        self.conn.execute(
            "DELETE FROM WorkTrackLinks WHERE work_id=? AND track_id=?",
            (ids["work_id"], ids["track_id"]),
        )

        by_type_expectations = {
            "work": {"Tracks", "Parties", "Contracts", "Rights"},
            "track": {"Works", "Releases", "Contracts", "Rights", "Assets"},
            "release": {"Tracks", "Contracts", "Rights", "Assets"},
            "contract": {"Parties", "Works", "Tracks", "Releases", "Rights", "Documents"},
            "party": {"Works", "Contracts", "Rights"},
            "right": {"Work", "Track", "Release", "Source Contract", "Parties"},
            "document": {"Contract"},
            "asset": {"Works", "Releases", "Contracts", "Rights", "Assets", "Tracks"},
        }
        entity_ids = {
            "work": ids["work_id"],
            "track": ids["track_id"],
            "release": ids["release_id"],
            "contract": ids["contract_id"],
            "party": ids["label_party_id"],
            "right": ids["right_id"],
            "document": ids["document_id"],
            "asset": ids["asset_id"],
        }
        for entity_type, expected_sections in by_type_expectations.items():
            with self.subTest(entity_type=entity_type):
                sections = self.relationship_service.describe_links(
                    entity_type, entity_ids[entity_type]
                )
                section_titles = {section.section_title for section in sections}
                self.assertTrue(expected_sections <= section_titles)

        work_sections = self.relationship_service.describe_links("work", ids["work_id"])
        work_track_section = next(
            section for section in work_sections if section.section_title == "Tracks"
        )
        self.assertEqual([item.entity_id for item in work_track_section.results], [ids["track_id"]])

        track_sections = self.relationship_service.describe_links("track", ids["track_id"])
        track_work_section = next(
            section for section in track_sections if section.section_title == "Works"
        )
        self.assertEqual([item.entity_id for item in track_work_section.results], [ids["work_id"]])
        self.assertEqual(self.relationship_service.describe_links("unknown", 99), [])

    def case_repertoire_exchange_json_round_trip(self):
        self._seed_repertoire()
        export_path = self.data_root / "repertoire.json"
        self.exchange_service.export_json(export_path)

        new_conn, new_services, imported_track_id, imported_release_id = (
            self._prepare_import_target(self.data_root)
        )
        try:
            self.assertEqual(imported_track_id, 1)
            self.assertEqual(imported_release_id, 1)
            new_services["exchange_service"].import_json(export_path)

            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 3)
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

    def case_repertoire_exchange_json_round_trip_preserves_expanded_party_metadata(self):
        ids = self._seed_repertoire()
        export_path = self.data_root / "repertoire-expanded-party.json"
        self.exchange_service.export_json(export_path)

        new_conn, new_services, imported_track_id, imported_release_id = (
            self._prepare_import_target(self.data_root)
        )
        try:
            self.assertEqual(imported_track_id, 1)
            self.assertEqual(imported_release_id, 1)
            new_services["exchange_service"].import_json(export_path)

            imported_party = new_services["party_service"].fetch_party(ids["label_party_id"])
            self.assertIsNotNone(imported_party)
            assert imported_party is not None
            self.assertEqual(imported_party.display_name, "Nova")
            self.assertEqual(imported_party.artist_name, "Nova Official")
            self.assertEqual(imported_party.company_name, "Nova Music Group")
            self.assertEqual(imported_party.alternative_email, "legal@nova.test")
            self.assertEqual(imported_party.street_name, "Canal Street")
            self.assertEqual(imported_party.street_number, "24")
            self.assertEqual(imported_party.chamber_of_commerce_number, "CoC-990011")
            self.assertEqual(imported_party.pro_number, "PRO-990011")
            self.assertEqual(
                imported_party.artist_aliases,
                ("Nova Alias", "Nova Stage Name"),
            )
        finally:
            new_conn.close()

    def case_repertoire_exchange_package_round_trip_preserves_files_and_document_chain(self):
        ids = self._seed_repertoire()
        original_detail = self.contract_service.fetch_contract_detail(ids["contract_id"])
        assert original_detail is not None
        signed_document = original_detail.documents[0]
        amendment_path = self.data_root / "amendment.txt"
        amendment_path.write_text("amendment content", encoding="utf-8")
        self.contract_service.update_contract(
            ids["contract_id"],
            ContractPayload(
                title="Nova Distribution Agreement",
                contract_type="distribution",
                status="active",
                parties=[
                    ContractPartyPayload(
                        party_id=ids["label_party_id"],
                        role_label="label",
                        is_primary=True,
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        document_id=signed_document.id,
                        title=signed_document.title,
                        document_type=signed_document.document_type,
                        active_flag=False,
                        signed_by_all_parties=True,
                        stored_path=signed_document.file_path,
                        filename=signed_document.filename,
                        checksum_sha256=signed_document.checksum_sha256,
                    ),
                    ContractDocumentPayload(
                        title="Amendment One",
                        document_type="amendment",
                        active_flag=True,
                        supersedes_document_id=signed_document.id,
                        source_path=str(amendment_path),
                    ),
                ],
                work_ids=[ids["work_id"]],
                track_ids=[ids["track_id"]],
                release_ids=[ids["release_id"]],
            ),
        )
        package_path = self.data_root / "repertoire-package.zip"
        self.exchange_service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())
        self.assertIn("manifest.json", names)
        self.assertTrue(any(name.startswith("files/contracts/") for name in names))
        self.assertTrue(any(name.startswith("files/assets/") for name in names))

        target_root = Path(tempfile.mkdtemp(prefix="repertoire-import-"))
        self.addCleanup(shutil.rmtree, target_root, True)
        new_conn, new_services, _track_id, _release_id = self._prepare_import_target(target_root)
        try:
            new_services["exchange_service"].import_package(package_path)
            imported_detail = new_services["contract_service"].fetch_contract_detail(1)
            assert imported_detail is not None
            self.assertEqual(len(imported_detail.documents), 2)
            amendment_doc = next(
                doc for doc in imported_detail.documents if doc.document_type == "amendment"
            )
            signed_doc = next(
                doc for doc in imported_detail.documents if doc.document_type == "signed_agreement"
            )
            self.assertEqual(amendment_doc.supersedes_document_id, signed_doc.id)

            for document in imported_detail.documents:
                resolved = new_services["contract_service"].resolve_document_path(
                    document.file_path
                )
                self.assertIsNotNone(resolved)
                assert resolved is not None
                self.assertTrue(resolved.exists())

            imported_asset = new_services["asset_service"].fetch_asset(1)
            self.assertIsNotNone(imported_asset)
            assert imported_asset is not None
            asset_path = new_services["asset_service"].resolve_asset_path(
                imported_asset.stored_path
            )
            self.assertIsNotNone(asset_path)
            assert asset_path is not None
            self.assertTrue(asset_path.exists())
            self.assertEqual(asset_path.read_bytes(), b"RIFFdemo")
        finally:
            new_conn.close()

    def case_repertoire_exchange_package_round_trip_preserves_database_backed_files(self):
        label_party_id = self.party_service.create_party(
            PartyPayload(legal_name="Blob Label", email="blob@label.test")
        )
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Binary Agreement Work",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Blob Label",
                        party_id=label_party_id,
                        share_percent=100,
                    )
                ],
            )
        )
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00027",
                track_title="Binary Attachment",
                artist_name="Blob Label",
                additional_artists=[],
                album_title="Binary Release",
                release_date="2026-03-16",
                track_length_sec=180,
                iswc=None,
                upc="036000291452",
                genre="Synth",
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Binary Release",
                primary_artist="Blob Label",
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
        document_path = self.data_root / "blob-contract.pdf"
        document_path.write_bytes(b"%PDF-blob-contract")
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Blob Contract",
                contract_type="distribution",
                status="active",
                parties=[
                    ContractPartyPayload(
                        party_id=label_party_id,
                        role_label="label",
                        is_primary=True,
                    )
                ],
                documents=[
                    ContractDocumentPayload(
                        title="Blob PDF",
                        document_type="signed_agreement",
                        source_path=str(document_path),
                        storage_mode="database",
                        signed_by_all_parties=True,
                        active_flag=True,
                    )
                ],
                work_ids=[work_id],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )
        asset_path = self.data_root / "blob-asset.wav"
        asset_path.write_bytes(b"RIFFblobasset")
        self.asset_service.create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(asset_path),
                storage_mode="database",
                approved_for_use=True,
                primary_flag=True,
                track_id=track_id,
                release_id=release_id,
            )
        )

        package_path = self.data_root / "repertoire-blob-package.zip"
        self.exchange_service.export_package(package_path)

        with ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())

        self.assertTrue(any(name.startswith("files/contracts/") for name in names))
        self.assertTrue(any(name.startswith("files/assets/") for name in names))

        target_root = Path(tempfile.mkdtemp(prefix="repertoire-blob-import-"))
        self.addCleanup(shutil.rmtree, target_root, True)
        new_conn, new_services, _track_id, _release_id = self._prepare_import_target(target_root)
        try:
            new_services["exchange_service"].import_package(package_path)

            imported_detail = new_services["contract_service"].fetch_contract_detail(contract_id)
            self.assertIsNotNone(imported_detail)
            assert imported_detail is not None
            self.assertEqual(len(imported_detail.documents), 1)
            imported_document = imported_detail.documents[0]
            self.assertEqual(imported_document.storage_mode, "database")
            self.assertIsNone(imported_document.file_path)
            document_bytes, _ = new_services["contract_service"].fetch_document_bytes(
                imported_document.id
            )
            self.assertEqual(document_bytes, b"%PDF-blob-contract")

            imported_asset = new_services["asset_service"].fetch_asset(1)
            self.assertIsNotNone(imported_asset)
            assert imported_asset is not None
            self.assertEqual(imported_asset.storage_mode, "database")
            self.assertIsNone(imported_asset.stored_path)
            asset_bytes, _ = new_services["asset_service"].fetch_asset_bytes(imported_asset.id)
            self.assertEqual(asset_bytes, b"RIFFblobasset")
        finally:
            new_conn.close()

    def case_repertoire_exchange_xlsx_csv_and_schema_validation(self):
        self._seed_repertoire()
        xlsx_path = self.data_root / "repertoire.xlsx"
        csv_dir = self.data_root / "csv-export"
        json_path = self.data_root / "invalid-repertoire.json"
        self.exchange_service.export_xlsx(xlsx_path)
        self.exchange_service.export_csv_bundle(csv_dir)
        json_path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

        xlsx_conn, xlsx_services, _track_id, _release_id = self._prepare_import_target(
            self.data_root
        )
        csv_conn, csv_services, _track_id_2, _release_id_2 = self._prepare_import_target(
            self.data_root
        )
        try:
            xlsx_services["exchange_service"].import_xlsx(xlsx_path)
            csv_services["exchange_service"].import_csv_bundle(csv_dir)

            self.assertEqual(xlsx_conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0], 1)
            self.assertEqual(csv_conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0], 1)
            self.assertEqual(
                xlsx_conn.execute("SELECT COUNT(*) FROM ContractDocuments").fetchone()[0],
                1,
            )
            self.assertEqual(
                csv_conn.execute("SELECT COUNT(*) FROM AssetVersions").fetchone()[0],
                1,
            )
            with self.assertRaises(ValueError):
                self.exchange_service.import_json(json_path)
        finally:
            xlsx_conn.close()
            csv_conn.close()

    def case_repertoire_inspection_previews_counts_without_writing(self):
        self._seed_repertoire()
        json_path = self.data_root / "repertoire-inspection.json"
        self.exchange_service.export_json(json_path)

        target_root = Path(tempfile.mkdtemp(prefix="repertoire-inspection-target-"))
        self.addCleanup(shutil.rmtree, target_root, True)
        new_conn, new_services, _track_id, _release_id = self._prepare_import_target(target_root)
        try:
            inspection = new_services["exchange_service"].inspect_json(json_path)
            self.assertEqual(inspection.format_name, "json")
            self.assertEqual(inspection.entity_counts["parties"], 3)
            self.assertEqual(inspection.entity_counts["works"], 1)
            self.assertGreaterEqual(len(inspection.preview_rows), 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Parties").fetchone()[0], 1)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0], 0)
            self.assertEqual(new_conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 0)
            self.assertEqual(
                new_conn.execute("SELECT COUNT(*) FROM RightsRecords").fetchone()[0],
                0,
            )
        finally:
            new_conn.close()

    def case_repertoire_import_reports_staged_progress_to_completion(self):
        self._seed_repertoire()
        json_path = self.data_root / "repertoire-progress.json"
        self.exchange_service.export_json(json_path)

        target_root = Path(tempfile.mkdtemp(prefix="repertoire-progress-import-"))
        self.addCleanup(shutil.rmtree, target_root, True)
        new_conn, new_services, _track_id, _release_id = self._prepare_import_target(target_root)
        progress_events: list[tuple[int, int, str]] = []
        try:
            new_services["exchange_service"].import_json(
                json_path,
                progress_callback=lambda value, maximum, message: progress_events.append(
                    (value, maximum, message)
                ),
            )
            self.assertGreaterEqual(len(progress_events), 5)
            self.assertEqual(progress_events[0][0], 5)
            self.assertEqual(
                progress_events[-1], (100, 100, "Contracts and Rights import complete.")
            )
            self.assertTrue(
                any("Importing Work records" in message for *_rest, message in progress_events)
            )
        finally:
            new_conn.close()

    def case_repertoire_export_reports_staged_progress(self):
        self._seed_repertoire()
        json_path = self.data_root / "repertoire-export-progress.json"
        progress_events: list[tuple[int, int, str]] = []

        self.exchange_service.export_json(
            json_path,
            progress_callback=lambda value, maximum, message: progress_events.append(
                (value, maximum, message)
            ),
        )

        self.assertTrue(json_path.exists())
        self.assertGreaterEqual(len(progress_events), 5)
        self.assertEqual(progress_events[0], (5, 100, "Collecting Party records for export..."))
        self.assertEqual(progress_events[-1], (90, 100, "Repertoire JSON written."))
        self.assertEqual(
            [value for value, _maximum, _message in progress_events],
            sorted(value for value, _maximum, _message in progress_events),
        )
        self.assertTrue(
            any("Collecting Work records" in message for *_rest, message in progress_events)
        )
        self.assertTrue(
            any(
                "Serializing repertoire JSON payload" in message
                for *_rest, message in progress_events
            )
        )


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite()

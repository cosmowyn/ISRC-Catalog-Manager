import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.history import HistoryManager
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.quality import QualityDashboardService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.services import (
    DatabaseMaintenanceService,
    DatabaseSchemaService,
    DatabaseSessionService,
    TrackCreatePayload,
    TrackService,
    TrackUpdatePayload,
)
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


class CatalogWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.data_root = self.root / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "Database" / "catalog.db"
        self.history_root = self.root / "history"
        self.backups_root = self.root / "backups"
        self.settings_path = self.root / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        self.session_service = DatabaseSessionService()
        self.session = self.session_service.open(self.db_path)
        self.conn = self.session.conn
        self._build_services(self.conn)

    def tearDown(self):
        self.settings.clear()
        self.session_service.close(getattr(self, "conn", None))
        self.tmpdir.cleanup()

    def _build_services(self, conn: sqlite3.Connection) -> None:
        schema = DatabaseSchemaService(conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(conn, self.data_root)
        self.release_service = ReleaseService(conn, self.data_root)
        self.party_service = PartyService(conn)
        self.work_service = WorkService(conn, party_service=self.party_service)
        self.contract_service = ContractService(
            conn, self.data_root, party_service=self.party_service
        )
        self.rights_service = RightsService(conn)
        self.asset_service = AssetService(conn, self.data_root)
        self.search_service = GlobalSearchService(conn)
        self.relationship_service = RelationshipExplorerService(conn)
        self.exchange_service = RepertoireExchangeService(
            conn,
            party_service=self.party_service,
            work_service=self.work_service,
            contract_service=self.contract_service,
            rights_service=self.rights_service,
            asset_service=self.asset_service,
            data_root=self.data_root,
        )
        self.quality_service = QualityDashboardService(
            conn,
            track_service=self.track_service,
            release_service=self.release_service,
            data_root=self.data_root,
        )
        self.history_manager = HistoryManager(
            conn,
            self.settings,
            self.db_path,
            self.history_root,
            self.data_root,
        )
        self.database_maintenance = DatabaseMaintenanceService(self.backups_root)

    def _seed_catalog(self) -> dict[str, int]:
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00201",
                track_title="Aurora Signal",
                artist_name="Nova Echo",
                additional_artists=["Guest Voice"],
                album_title="Northern Lights",
                release_date="2026-03-16",
                track_length_sec=243,
                iswc="T-201.301.401-2",
                upc="036000291452",
                genre="Electronic",
                composer="Nova Echo",
                publisher="Aurora Publishing",
            )
        )
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Northern Lights",
                primary_artist="Nova Echo",
                release_type="album",
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
        party_id = self.party_service.create_party(
            PartyPayload(legal_name="Aurora Publishing", email="catalog@aurora.test")
        )
        work_id = self.work_service.create_work(
            WorkPayload(
                title="Aurora Signal",
                iswc="T-201.301.401-2",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Aurora Publishing",
                        party_id=party_id,
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )
        document_path = self.root / "aurora-agreement.txt"
        document_path.write_text("signed agreement", encoding="utf-8")
        contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Aurora Distribution Agreement",
                contract_type="distribution",
                status="active",
                parties=[
                    ContractPartyPayload(
                        party_id=party_id,
                        role_label="publisher",
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
        right_id = self.rights_service.create_right(
            RightPayload(
                title="Aurora Master Right",
                right_type="master",
                territory="Worldwide",
                source_contract_id=contract_id,
                exclusive_flag=True,
                granted_to_party_id=party_id,
                retained_by_party_id=party_id,
                work_id=work_id,
                track_id=track_id,
                release_id=release_id,
            )
        )
        asset_path = self.root / "aurora-master.wav"
        asset_path.write_bytes(b"RIFFaurora")
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
        incomplete_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00202",
                track_title="Draft Echo",
                artist_name="Nova Echo",
                additional_artists=[],
                album_title="Northern Lights",
                release_date="2026-03-16",
                track_length_sec=210,
                iswc=None,
                upc="036000291452",
                genre="Electronic",
                composer="Unlinked Writer",
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
            "incomplete_track_id": incomplete_track_id,
        }

    def test_profile_round_trip_preserves_repertoire_links_search_and_quality(self):
        ids = self._seed_catalog()
        self.session_service.close(self.conn)

        reopened = self.session_service.open(self.db_path)
        self.conn = reopened.conn
        self._build_services(self.conn)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Tracks").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM RightsRecords").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM AssetVersions").fetchone()[0], 1)

        results = self.search_service.search("Aurora")
        self.assertTrue(any(item.entity_type == "track" for item in results))
        self.assertTrue(any(item.entity_type == "work" for item in results))
        self.assertTrue(any(item.entity_type == "contract" for item in results))

        self.conn.execute(
            "DELETE FROM WorkTrackLinks WHERE work_id=? AND track_id=?",
            (ids["work_id"], ids["track_id"]),
        )

        sections = self.relationship_service.describe_links("track", ids["track_id"])
        section_titles = {section.section_title for section in sections}
        self.assertTrue({"Works", "Releases", "Contracts", "Rights", "Assets"} <= section_titles)
        work_section = next(section for section in sections if section.section_title == "Works")
        self.assertEqual([item.entity_id for item in work_section.results], [ids["work_id"]])

        work_sections = self.relationship_service.describe_links("work", ids["work_id"])
        track_section = next(section for section in work_sections if section.section_title == "Tracks")
        self.assertEqual([item.entity_id for item in track_section.results], [ids["track_id"]])

        scan = self.quality_service.scan()
        issue_types = {issue.issue_type for issue in scan.issues}
        self.assertIn("track_missing_linked_work", issue_types)

    def test_backup_restore_and_repertoire_import_round_trip(self):
        ids = self._seed_catalog()
        snapshot = self.history_manager.create_manual_snapshot("Catalog Ready")
        self.assertGreater(snapshot.snapshot_id, 0)

        export_path = self.root / "repertoire.json"
        self.exchange_service.export_json(export_path)
        self.assertTrue(export_path.exists())

        backup = self.database_maintenance.create_backup(self.conn, self.db_path)
        self.track_service.update_track(
            TrackUpdatePayload(
                track_id=ids["track_id"],
                isrc="NL-ABC-26-00201",
                track_title="Corrupted Title",
                artist_name="Nova Echo",
                additional_artists=["Guest Voice"],
                album_title="Northern Lights",
                release_date="2026-03-16",
                track_length_sec=243,
                iswc="T-201.301.401-2",
                upc="036000291452",
                genre="Electronic",
                composer="Nova Echo",
                publisher="Aurora Publishing",
            )
        )
        self.session_service.close(self.conn)

        restored = self.database_maintenance.restore_database(backup.backup_path, self.db_path)
        self.assertEqual(restored.integrity_result, "ok")

        reopened = self.session_service.open(self.db_path)
        self.conn = reopened.conn
        self._build_services(self.conn)

        snapshot = self.track_service.fetch_track_snapshot(ids["track_id"])
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.track_title, "Aurora Signal")

        imported_db = self.root / "Database" / "imported.db"
        imported_session = self.session_service.open(imported_db)
        try:
            imported_schema = DatabaseSchemaService(imported_session.conn, data_root=self.data_root)
            imported_schema.init_db()
            imported_schema.migrate_schema()
            imported_track_service = TrackService(imported_session.conn, self.data_root)
            imported_release_service = ReleaseService(imported_session.conn, self.data_root)
            imported_track_id = imported_track_service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00201",
                    track_title="Aurora Signal",
                    artist_name="Nova Echo",
                    additional_artists=["Guest Voice"],
                    album_title="Northern Lights",
                    release_date="2026-03-16",
                    track_length_sec=243,
                    iswc="T-201.301.401-2",
                    upc="036000291452",
                    genre="Electronic",
                )
            )
            imported_release_service.create_release(
                ReleasePayload(
                    title="Northern Lights",
                    primary_artist="Nova Echo",
                    release_type="album",
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
            imported_party_service = PartyService(imported_session.conn)
            imported_exchange = RepertoireExchangeService(
                imported_session.conn,
                party_service=imported_party_service,
                work_service=WorkService(
                    imported_session.conn, party_service=imported_party_service
                ),
                contract_service=ContractService(
                    imported_session.conn,
                    self.data_root,
                    party_service=imported_party_service,
                ),
                rights_service=RightsService(imported_session.conn),
                asset_service=AssetService(imported_session.conn, self.data_root),
                data_root=self.data_root,
            )
            imported_exchange.import_json(export_path)
            self.assertEqual(
                imported_session.conn.execute("SELECT COUNT(*) FROM Works").fetchone()[0],
                1,
            )
            self.assertEqual(
                imported_session.conn.execute("SELECT COUNT(*) FROM Contracts").fetchone()[0],
                1,
            )
            self.assertEqual(
                imported_session.conn.execute("SELECT COUNT(*) FROM RightsRecords").fetchone()[0],
                1,
            )
            self.assertEqual(
                imported_session.conn.execute("SELECT COUNT(*) FROM AssetVersions").fetchone()[0],
                1,
            )
        finally:
            self.session_service.close(imported_session.conn)


if __name__ == "__main__":
    unittest.main()

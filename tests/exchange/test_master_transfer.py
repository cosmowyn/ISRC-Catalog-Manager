import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contract_templates import (
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
)
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.exchange import ExchangeService, MasterTransferService, RepertoireExchangeService
from isrc_manager.parties import PartyPayload, PartyService
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
from tests.contract_templates._support import make_docx_bytes


class MasterTransferServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.contexts: list[dict[str, object]] = []
        self.source = self._build_context(self.root / "source")
        self.source_ids = self._seed_source_dataset(self.source)

    def tearDown(self):
        for ctx in reversed(self.contexts):
            try:
                ctx["conn"].close()
            except Exception:
                pass
        self.tmpdir.cleanup()

    def _build_context(self, data_root: Path) -> dict[str, object]:
        data_root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
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
        custom_defs = CustomFieldDefinitionService(conn)
        license_service = LicenseService(conn, data_root)
        contract_template_service = ContractTemplateService(conn, data_root)
        exchange_service = ExchangeService(
            conn,
            track_service,
            release_service,
            custom_defs,
            data_root,
            party_service=party_service,
            work_service=work_service,
        )
        repertoire_service = RepertoireExchangeService(
            conn,
            party_service=party_service,
            work_service=work_service,
            contract_service=contract_service,
            rights_service=rights_service,
            asset_service=asset_service,
            data_root=data_root,
        )
        master_transfer_service = MasterTransferService(
            exchange_service=exchange_service,
            repertoire_exchange_service=repertoire_service,
            license_service=license_service,
            contract_template_service=contract_template_service,
            app_version="9.9.9-test",
        )
        ctx = {
            "conn": conn,
            "data_root": data_root,
            "track_service": track_service,
            "release_service": release_service,
            "party_service": party_service,
            "work_service": work_service,
            "contract_service": contract_service,
            "rights_service": rights_service,
            "asset_service": asset_service,
            "license_service": license_service,
            "contract_template_service": contract_template_service,
            "exchange_service": exchange_service,
            "repertoire_service": repertoire_service,
            "master_transfer_service": master_transfer_service,
        }
        self.contexts.append(ctx)
        return ctx

    def _seed_source_dataset(self, ctx: dict[str, object]) -> dict[str, int]:
        data_root = ctx["data_root"]
        license_path = data_root / "license.pdf"
        license_path.write_bytes(b"%PDF-1.4\nmaster transfer license\n")
        contract_doc_path = data_root / "distribution-agreement.txt"
        contract_doc_path.write_text("signed distribution agreement", encoding="utf-8")

        track_id = ctx["track_service"].create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-20001",
                track_title="Midnight Circuit",
                artist_name="Nova",
                additional_artists=["Control"],
                album_title="Night Runs",
                release_date="2026-03-16",
                track_length_sec=222,
                iswc="T-222.333.444-5",
                upc="036000291452",
                genre="Synthwave",
                catalog_number="CAT-9001",
                buma_work_number="WORK-9001",
                composer="Nova Writer",
                publisher="Nova Music",
            )
        )
        release_id = ctx["release_service"].create_release(
            ReleasePayload(
                title="Night Runs",
                primary_artist="Nova",
                album_artist="Nova",
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
        label_party_id = ctx["party_service"].create_party(
            PartyPayload(
                legal_name="Nova Music",
                display_name="Nova Music",
                artist_name="Nova",
                company_name="Nova Music Group",
            )
        )
        control_party_id = ctx["party_service"].create_party(
            PartyPayload(legal_name="Orbit Rights Control")
        )
        work_id = ctx["work_service"].create_work(
            WorkPayload(
                title="Midnight Circuit",
                iswc="T-222.333.444-5",
                registration_number="WORK-9001",
                contributors=[
                    WorkContributorPayload(
                        role="songwriter",
                        name="Nova Writer",
                        party_id=label_party_id,
                        share_percent=100,
                    )
                ],
                track_ids=[track_id],
            )
        )
        base_contract_id = ctx["contract_service"].create_contract(
            ContractPayload(
                title="Nova Distribution Agreement",
                contract_type="distribution",
                status="superseded",
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
                        source_path=str(contract_doc_path),
                        signed_by_all_parties=True,
                        active_flag=True,
                    )
                ],
                work_ids=[work_id],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )
        amendment_contract_id = ctx["contract_service"].create_contract(
            ContractPayload(
                title="Nova Distribution Amendment",
                contract_type="distribution",
                status="active",
                supersedes_contract_id=base_contract_id,
                parties=[
                    ContractPartyPayload(
                        party_id=label_party_id,
                        role_label="label",
                        is_primary=True,
                    )
                ],
                work_ids=[work_id],
                track_ids=[track_id],
                release_ids=[release_id],
            )
        )
        right_id = ctx["rights_service"].create_right(
            RightPayload(
                title="Master Distribution Right",
                right_type="master",
                exclusive_flag=True,
                territory="Worldwide",
                granted_by_party_id=label_party_id,
                granted_to_party_id=control_party_id,
                retained_by_party_id=label_party_id,
                source_contract_id=amendment_contract_id,
                work_id=work_id,
                track_id=track_id,
                release_id=release_id,
            )
        )
        master_asset_path = data_root / "midnight-master.wav"
        master_asset_path.write_bytes(b"RIFFprimary-master")
        master_asset_id = ctx["asset_service"].create_asset(
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(master_asset_path),
                approved_for_use=True,
                primary_flag=True,
                track_id=track_id,
                release_id=release_id,
            )
        )
        derivative_asset_path = data_root / "midnight-derivative.mp3"
        derivative_asset_path.write_bytes(b"ID3derivative")
        derivative_asset_id = ctx["asset_service"].create_asset(
            AssetVersionPayload(
                asset_type="mp3_derivative",
                source_path=str(derivative_asset_path),
                derived_from_asset_id=master_asset_id,
                track_id=track_id,
                release_id=release_id,
            )
        )
        license_id = ctx["license_service"].add_license(
            track_id=track_id,
            licensee_name="Moonwake Rights",
            source_pdf_path=license_path,
        )
        template = ctx["contract_template_service"].create_template(
            ContractTemplatePayload(
                name="Artist Agreement",
                template_family="contract",
                source_format="docx",
            )
        )
        import_result = ctx["contract_template_service"].import_revision_from_bytes(
            template.template_id,
            make_docx_bytes(
                document_paragraphs=("Agreement for {{db.track.track_title}}",),
            ),
            payload=ContractTemplateRevisionPayload(
                source_filename="artist-agreement.docx",
                source_format="docx",
            ),
        )
        return {
            "track_id": track_id,
            "release_id": release_id,
            "label_party_id": label_party_id,
            "control_party_id": control_party_id,
            "work_id": work_id,
            "base_contract_id": base_contract_id,
            "amendment_contract_id": amendment_contract_id,
            "right_id": right_id,
            "master_asset_id": master_asset_id,
            "derivative_asset_id": derivative_asset_id,
            "license_id": license_id,
            "template_id": template.template_id,
            "revision_id": import_result.revision.revision_id,
        }

    def _create_dummy_target_entities(self, ctx: dict[str, object]) -> None:
        ctx["party_service"].create_party(PartyPayload(legal_name="Existing Target Party"))
        ctx["track_service"].create_track(
            TrackCreatePayload(
                isrc="NL-TGT-26-00001",
                track_title="Existing Target Track",
                artist_name="Already Here",
                additional_artists=[],
                album_title="Existing Album",
                release_date="2026-01-01",
                track_length_sec=111,
                iswc="T-000.000.000-1",
                upc="036000291469",
                genre="Ambient",
            )
        )

    def _count(self, ctx: dict[str, object], table_name: str) -> int:
        row = ctx["conn"].execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return int(row[0] or 0) if row is not None else 0

    def _rewrite_package(self, source_path: Path, *, mutate_root) -> Path:
        rewritten = self.root / f"rewritten-{source_path.name}"
        with tempfile.TemporaryDirectory(prefix="master-transfer-rewrite-") as temp_dir:
            extracted_root = Path(temp_dir)
            with ZipFile(source_path, "r") as archive:
                archive.extractall(extracted_root)
            mutate_root(extracted_root)
            with ZipFile(rewritten, "w", compression=ZIP_DEFLATED) as archive:
                for file_path in sorted(
                    path for path in extracted_root.rglob("*") if path.is_file()
                ):
                    archive.write(
                        file_path, arcname=file_path.relative_to(extracted_root).as_posix()
                    )
        return rewritten

    def test_master_transfer_export_writes_versioned_manifest_and_sections(self):
        package_path = self.root / "master-transfer.zip"
        result = self.source["master_transfer_service"].export_package(package_path)

        self.assertTrue(package_path.exists())
        self.assertEqual(result.app_version, "9.9.9-test")
        self.assertEqual(
            {section.section_id for section in result.sections},
            {
                "catalog",
                "repertoire",
                "licenses",
                "contract_templates",
            },
        )
        with ZipFile(package_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["document_type"], "master_transfer_package")
            self.assertEqual(manifest["package_format"], "logical_catalog_transfer")
            self.assertEqual(manifest["package_format_version"], 1)
            self.assertEqual(
                {section["section_id"] for section in manifest["sections"]},
                {
                    "catalog",
                    "repertoire",
                    "licenses",
                    "contract_templates",
                },
            )
            file_paths = {entry["path"] for entry in manifest["files"]}
            self.assertIn("sections/catalog/package.zip", file_paths)
            self.assertIn("sections/repertoire/package.zip", file_paths)
            self.assertIn("sections/licenses/licenses.json", file_paths)
            self.assertIn("sections/contract_templates/templates.json", file_paths)
            self.assertTrue(any(path.startswith("sections/licenses/files/") for path in file_paths))
            self.assertTrue(
                any(path.startswith("sections/contract_templates/files/") for path in file_paths)
            )

    def test_master_transfer_inspection_previews_contents_without_writing(self):
        package_path = self.root / "master-transfer.zip"
        self.source["master_transfer_service"].export_package(package_path)
        target = self._build_context(self.root / "inspect-target")

        inspection = target["master_transfer_service"].inspect_package(package_path)

        self.assertTrue(any("Included sections:" in line for line in inspection.summary_lines))
        preview_sections = {str(row.get("Section") or "") for row in inspection.preview_rows}
        self.assertIn("Catalog", preview_sections)
        self.assertIn("Contracts and Rights", preview_sections)
        self.assertIn("License Archive", preview_sections)
        self.assertIn("Contract Templates", preview_sections)
        self.assertEqual(self._count(target, "Tracks"), 0)
        self.assertEqual(self._count(target, "Works"), 0)
        self.assertEqual(self._count(target, "Contracts"), 0)
        self.assertEqual(self._count(target, "Licenses"), 0)
        self.assertEqual(self._count(target, "ContractTemplates"), 0)

    def test_master_transfer_export_surfaces_missing_release_artwork_as_warning(self):
        artwork_path = self.root / "source" / "broken-master-release.png"
        artwork_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A"
                "0000000D49484452000000010000000108060000001F15C489"
                "0000000D49444154789C63606060000000050001F56E27D4"
                "0000000049454E44AE426082"
            )
        )
        release_service = self.source["release_service"]
        release_id = self.source_ids["release_id"]
        release = release_service.fetch_release(release_id)
        summary = release_service.fetch_release_summary(release_id)
        release_service.update_release(
            release_id,
            ReleasePayload(
                title=release.title,
                version_subtitle=release.version_subtitle,
                primary_artist=release.primary_artist,
                album_artist=release.album_artist,
                release_type=release.release_type,
                release_date=release.release_date,
                original_release_date=release.original_release_date,
                label=release.label,
                sublabel=release.sublabel,
                catalog_number=release.catalog_number,
                upc=release.upc,
                territory=release.territory,
                explicit_flag=release.explicit_flag,
                notes=release.notes,
                artwork_source_path=str(artwork_path),
                placements=list(summary.tracks),
            ),
        )
        updated = release_service.fetch_release(release_id)
        managed_path = release_service.resolve_artwork_path(updated.artwork_path)
        self.assertIsNotNone(managed_path)
        managed_path.unlink()

        package_path = self.root / "master-transfer-broken-artwork.zip"
        result = self.source["master_transfer_service"].export_package(package_path)
        inspection = self.source["master_transfer_service"].inspect_package(package_path)

        self.assertTrue(
            any("omitted release artwork" in warning.lower() for warning in result.warnings)
        )
        self.assertTrue(
            any("omitted release artwork" in warning.lower() for warning in inspection.warnings)
        )
        with ZipFile(package_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertTrue(
            any(
                "omitted release artwork" in str(warning).lower()
                for warning in manifest.get("warnings") or []
            )
        )

    def test_master_transfer_import_round_trip_rehydrates_sections_via_real_logic(self):
        package_path = self.root / "master-transfer.zip"
        self.source["master_transfer_service"].export_package(package_path)
        target = self._build_context(self.root / "import-target")
        self._create_dummy_target_entities(target)

        with (
            mock.patch.object(
                target["exchange_service"],
                "import_package",
                wraps=target["exchange_service"].import_package,
            ) as catalog_import,
            mock.patch.object(
                target["repertoire_service"],
                "import_package",
                wraps=target["repertoire_service"].import_package,
            ) as repertoire_import,
            mock.patch.object(
                target["license_service"],
                "add_license",
                wraps=target["license_service"].add_license,
            ) as add_license,
            mock.patch.object(
                target["contract_template_service"],
                "import_revision_from_bytes",
                wraps=target["contract_template_service"].import_revision_from_bytes,
            ) as import_revision,
        ):
            result = target["master_transfer_service"].import_package(package_path)

        self.assertGreaterEqual(catalog_import.call_count, 1)
        self.assertEqual(repertoire_import.call_count, 2)
        self.assertEqual(add_license.call_count, 1)
        self.assertEqual(import_revision.call_count, 1)
        self.assertEqual(self._count(target, "Tracks"), 2)
        self.assertEqual(self._count(target, "Works"), 1)
        self.assertEqual(self._count(target, "Contracts"), 2)
        self.assertEqual(self._count(target, "RightsRecords"), 1)
        self.assertEqual(self._count(target, "AssetVersions"), 2)
        self.assertEqual(self._count(target, "Licenses"), 1)
        self.assertEqual(self._count(target, "ContractTemplates"), 1)

        source_track_id = self.source_ids["track_id"]
        imported_track_id = result.catalog_report.source_track_id_map[source_track_id]
        self.assertNotEqual(imported_track_id, source_track_id)

        source_release_id = self.source_ids["release_id"]
        imported_release_id = result.catalog_report.source_release_id_map[source_release_id]
        right_row = (
            target["conn"]
            .execute(
                """
            SELECT track_id, release_id, source_contract_id
            FROM RightsRecords
            ORDER BY id
            LIMIT 1
            """
            )
            .fetchone()
        )
        self.assertEqual((right_row[0], right_row[1]), (imported_track_id, imported_release_id))

        source_base_contract_id = self.source_ids["base_contract_id"]
        source_amendment_contract_id = self.source_ids["amendment_contract_id"]
        imported_base_contract_id = int(
            result.repertoire_report.source_contract_id_map[str(source_base_contract_id)]
        )
        imported_amendment_contract_id = int(
            result.repertoire_report.source_contract_id_map[str(source_amendment_contract_id)]
        )
        contract_row = (
            target["conn"]
            .execute(
                """
            SELECT supersedes_contract_id
            FROM Contracts
            WHERE id=?
            """,
                (imported_amendment_contract_id,),
            )
            .fetchone()
        )
        self.assertEqual(int(contract_row[0]), imported_base_contract_id)

        source_master_asset_id = self.source_ids["master_asset_id"]
        source_derivative_asset_id = self.source_ids["derivative_asset_id"]
        imported_master_asset_id = int(
            result.repertoire_report.source_asset_id_map[str(source_master_asset_id)]
        )
        imported_derivative_asset_id = int(
            result.repertoire_report.source_asset_id_map[str(source_derivative_asset_id)]
        )
        asset_row = (
            target["conn"]
            .execute(
                """
            SELECT derived_from_asset_id
            FROM AssetVersions
            WHERE id=?
            """,
                (imported_derivative_asset_id,),
            )
            .fetchone()
        )
        self.assertEqual(int(asset_row[0]), imported_master_asset_id)

        license_row = (
            target["conn"].execute("SELECT track_id FROM Licenses ORDER BY id LIMIT 1").fetchone()
        )
        self.assertEqual(int(license_row[0]), imported_track_id)
        self.assertEqual(result.imported_licenses, 1)
        self.assertEqual(result.imported_contract_templates, 1)
        self.assertEqual(result.imported_template_revisions, 1)

    def test_master_transfer_detects_checksum_mismatch(self):
        package_path = self.root / "master-transfer.zip"
        self.source["master_transfer_service"].export_package(package_path)
        corrupted_path = self._rewrite_package(
            package_path,
            mutate_root=lambda extracted_root: (
                extracted_root / "sections" / "licenses" / "licenses.json"
            ).write_text(
                json.dumps({"schema_version": 1, "rows": []}, indent=2),
                encoding="utf-8",
            ),
        )

        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.source["master_transfer_service"].inspect_package(corrupted_path)

    def test_master_transfer_reports_staged_progress_to_completion(self):
        package_path = self.root / "master-transfer.zip"
        export_progress: list[tuple[int, int, str]] = []
        self.source["master_transfer_service"].export_package(
            package_path,
            progress_callback=lambda value, maximum, message: export_progress.append(
                (value, maximum, message)
            ),
        )

        target = self._build_context(self.root / "progress-target")
        import_progress: list[tuple[int, int, str]] = []
        target["master_transfer_service"].import_package(
            package_path,
            progress_callback=lambda value, maximum, message: import_progress.append(
                (value, maximum, message)
            ),
        )

        self.assertGreaterEqual(len(export_progress), 5)
        self.assertEqual(export_progress[-1], (100, 100, "Master transfer export package written."))
        self.assertEqual(
            [value for value, _maximum, _message in export_progress],
            sorted(value for value, _maximum, _message in export_progress),
        )
        self.assertTrue(
            any(
                "Building catalog exchange section" in message
                for *_rest, message in export_progress
            )
        )

        self.assertGreaterEqual(len(import_progress), 5)
        self.assertEqual(import_progress[-1], (100, 100, "Master transfer import complete."))
        self.assertEqual(
            [value for value, _maximum, _message in import_progress],
            sorted(value for value, _maximum, _message in import_progress),
        )
        self.assertTrue(
            any(
                "Seeding Party references from Contracts and Rights" in message
                for *_rest, message in import_progress
            )
        )
        self.assertTrue(
            any("Importing contract templates" in message for *_rest, message in import_progress)
        )


if __name__ == "__main__":
    unittest.main()

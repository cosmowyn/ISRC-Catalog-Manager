import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook
from PySide6.QtCore import QSettings

from isrc_manager.parties import (
    PartyExchangeService,
    PartyImportOptions,
    PartyPayload,
    PartyService,
)
from isrc_manager.services import (
    DatabaseSchemaService,
    SettingsMutationService,
    SettingsReadService,
)


class PartyExchangeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        settings_path = self.data_root / "party-exchange.ini"
        self.settings = QSettings(str(settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.party_service = PartyService(self.conn)
        self.settings_reads = SettingsReadService(self.conn)
        self.settings_mutations = SettingsMutationService(self.conn, self.settings)
        self.exchange_service = PartyExchangeService(
            self.conn,
            party_service=self.party_service,
            settings_mutations=self.settings_mutations,
            profile_name="TestProfile.db",
        )

    def tearDown(self):
        self.settings.sync()
        self.conn.close()
        self.tmpdir.cleanup()

    def test_export_selected_and_full_catalog_across_supported_formats(self):
        selected_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Aeonium",
                artist_name="Aeonium Official",
                email="hello@aeonium.test",
                artist_aliases=["Aeonium", "Lyra Cosmos"],
            )
        )
        other_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="North Star Music B.V.",
                display_name="North Star",
                chamber_of_commerce_number="COC-778899",
            )
        )
        self.settings_mutations.set_owner_party_id(other_party_id)

        json_path = self.data_root / "party-catalog.json"
        csv_path = self.data_root / "selected-parties.csv"
        xlsx_path = self.data_root / "selected-parties.xlsx"

        self.assertEqual(self.exchange_service.export_json(json_path), 2)
        self.assertEqual(self.exchange_service.export_csv(csv_path, [selected_party_id]), 1)
        self.assertEqual(self.exchange_service.export_xlsx(xlsx_path, [selected_party_id]), 1)

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["rows"]), 2)
        owner_rows = [row for row in payload["rows"] if row.get("is_owner")]
        self.assertEqual(len(owner_rows), 1)
        self.assertEqual(owner_rows[0]["id"], other_party_id)

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], str(selected_party_id))
        self.assertEqual(json.loads(rows[0]["artist_aliases"]), ["Aeonium", "Lyra Cosmos"])
        self.assertEqual(rows[0]["is_owner"], "False")

        workbook = load_workbook(filename=str(xlsx_path), read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.iter_rows(values_only=True))
        headers = list(values[0])
        body = values[1]
        self.assertEqual(sheet.title, "PartyCatalog")
        self.assertEqual(body[headers.index("id")], selected_party_id)
        self.assertEqual(body[headers.index("legal_name")], "Aeonium Holdings B.V.")

    def test_import_csv_creates_new_party_with_mapping_and_owner_binding(self):
        csv_path = self.data_root / "parties.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Legal Name,Display Name,Artist Aliases,Email Address,Party Type,Owner",
                    'Aeonium Holdings B.V.,Aeonium,"Aeonium | Lyra Cosmos",hello@aeonium.test,artist,true',
                ]
            ),
            encoding="utf-8",
        )

        inspection = self.exchange_service.inspect_csv(csv_path)
        report = self.exchange_service.import_csv(
            csv_path,
            mapping=inspection.suggested_mapping,
            options=PartyImportOptions(mode="upsert"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(len(report.created_parties), 1)
        party = self.party_service.fetch_party(report.created_parties[0])
        assert party is not None
        self.assertEqual(party.display_name, "Aeonium")
        self.assertEqual(list(party.artist_aliases), ["Aeonium", "Lyra Cosmos"])
        self.assertEqual(party.profile_name, "TestProfile.db")
        self.assertEqual(self.settings_reads.load_owner_party_id(), party.id)

    def test_import_xlsx_round_trip_preserves_aliases_and_business_fields(self):
        source_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="North Star Music B.V.",
                display_name="North Star",
                alternative_email="legal@northstar.test",
                chamber_of_commerce_number="COC-998877",
                pro_number="PRO-998877",
                artist_aliases=["North Star", "NSM"],
            )
        )
        xlsx_path = self.data_root / "party-catalog.xlsx"
        self.exchange_service.export_xlsx(xlsx_path, [source_party_id])

        other_conn = sqlite3.connect(":memory:")
        other_conn.execute("PRAGMA foreign_keys = ON")
        try:
            schema = DatabaseSchemaService(other_conn, data_root=self.data_root / "other")
            schema.init_db()
            schema.migrate_schema()
            other_settings = QSettings(str(self.data_root / "other.ini"), QSettings.IniFormat)
            other_party_service = PartyService(other_conn)
            other_service = PartyExchangeService(
                other_conn,
                party_service=other_party_service,
                settings_mutations=SettingsMutationService(other_conn, other_settings),
                profile_name="Imported.db",
            )
            inspection = other_service.inspect_xlsx(xlsx_path)
            report = other_service.import_xlsx(
                xlsx_path,
                mapping=inspection.suggested_mapping,
                options=PartyImportOptions(mode="upsert"),
            )
            self.assertEqual(report.passed, 1)
            imported = other_party_service.fetch_party(report.created_parties[0])
            assert imported is not None
            self.assertEqual(imported.alternative_email, "legal@northstar.test")
            self.assertEqual(imported.chamber_of_commerce_number, "COC-998877")
            self.assertEqual(imported.pro_number, "PRO-998877")
            self.assertEqual(list(imported.artist_aliases), ["North Star", "NSM"])
        finally:
            other_conn.close()

    def test_import_json_can_update_existing_party_by_safe_match(self):
        existing_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Old Aeonium",
                artist_name="Aeonium Official",
                email="hello@aeonium.test",
                artist_aliases=["Aeonium"],
            )
        )
        json_path = self.data_root / "party-update.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "columns": [
                        "legal_name",
                        "display_name",
                        "artist_aliases",
                        "email",
                    ],
                    "rows": [
                        {
                            "legal_name": "Aeonium Holdings B.V.",
                            "display_name": "Aeonium",
                            "artist_aliases": ["Aeonium", "Lyra Cosmos"],
                            "email": "hello@aeonium.test",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        inspection = self.exchange_service.inspect_json(json_path)
        report = self.exchange_service.import_json(
            json_path,
            mapping=inspection.suggested_mapping,
            options=PartyImportOptions(mode="upsert"),
        )

        self.assertEqual(report.passed, 1)
        self.assertEqual(report.created_parties, [])
        self.assertEqual(report.updated_parties, [existing_party_id])
        party = self.party_service.fetch_party(existing_party_id)
        assert party is not None
        self.assertEqual(party.display_name, "Aeonium")
        self.assertEqual(list(party.artist_aliases), ["Aeonium", "Lyra Cosmos"])

    def test_import_rejects_ambiguous_matches_instead_of_guessing(self):
        self.party_service.create_party(PartyPayload(legal_name="Duplicate Name"))
        self.party_service.create_party(PartyPayload(legal_name="Duplicate Name"))
        json_path = self.data_root / "party-ambiguous.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rows": [
                        {
                            "legal_name": "Duplicate Name",
                            "display_name": "Duplicate Name",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        inspection = self.exchange_service.inspect_json(json_path)
        report = self.exchange_service.import_json(
            json_path,
            mapping=inspection.suggested_mapping,
            options=PartyImportOptions(mode="upsert"),
        )

        self.assertEqual(report.passed, 0)
        self.assertEqual(report.failed, 1)
        self.assertIn("multiple existing Parties", "\n".join(report.warnings))

    def test_import_rejects_multiple_owner_rows_to_preserve_single_owner_integrity(self):
        json_path = self.data_root / "party-owner-conflict.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rows": [
                        {"legal_name": "Owner One", "is_owner": True},
                        {"legal_name": "Owner Two", "is_owner": True},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        inspection = self.exchange_service.inspect_json(json_path)
        report = self.exchange_service.import_json(
            json_path,
            mapping=inspection.suggested_mapping,
            options=PartyImportOptions(mode="upsert"),
        )

        self.assertEqual(report.passed, 0)
        self.assertEqual(report.failed, 2)
        self.assertIsNone(self.settings_reads.load_owner_party_id())
        self.assertEqual(self.party_service.list_parties(), [])

    def test_import_reports_staged_progress_to_completion(self):
        json_path = self.data_root / "party-progress.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rows": [
                        {
                            "legal_name": "Progress Party B.V.",
                            "display_name": "Progress Party",
                            "email": "hello@progress.test",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        inspection = self.exchange_service.inspect_json(json_path)
        progress_events: list[tuple[int, int, str]] = []

        report = self.exchange_service.import_json(
            json_path,
            mapping=inspection.suggested_mapping,
            options=PartyImportOptions(mode="upsert"),
            progress_callback=lambda value, maximum, message: progress_events.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(report.failed, 0)
        self.assertGreaterEqual(len(progress_events), 4)
        self.assertEqual(progress_events[0][0], 5)
        self.assertEqual(progress_events[-1], (100, 100, "Party import complete."))
        self.assertTrue(
            any("Creating and updating Parties" in message for *_rest, message in progress_events)
        )

import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from PySide6.QtCore import QSettings

from isrc_manager.services import GS1ContractEntry, GS1ProfileDefaults, GS1SettingsService


def make_settings_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE app_kv (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    return conn


def build_template(path: Path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "10070050"
    sheet["A1"] = "GS1 Artikelcode (GTIN)"
    workbook.save(path)


class GS1SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_settings_conn()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.service = GS1SettingsService(self.conn, self.settings)

    def tearDown(self):
        self.settings.clear()
        self.conn.close()
        self.tmpdir.cleanup()

    def test_template_path_is_stored_in_qsettings(self):
        saved = self.service.set_template_path("/tmp/official-gs1-template.xlsx")

        self.assertEqual(saved, "/tmp/official-gs1-template.xlsx")
        self.assertEqual(self.service.load_template_path(), "/tmp/official-gs1-template.xlsx")
        self.assertEqual(
            self.settings.value("gs1/template_path", "", str),
            "/tmp/official-gs1-template.xlsx",
        )

    def test_profile_defaults_round_trip_through_app_kv(self):
        saved = self.service.set_profile_defaults(
            GS1ProfileDefaults(
                contract_number="10070050",
                target_market="Worldwide",
                language="English",
                brand="Orbit Label",
                subbrand="Digital Series",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )

        self.assertEqual(
            saved,
            GS1ProfileDefaults(
                contract_number="10070050",
                target_market="Worldwide",
                language="English",
                brand="Orbit Label",
                subbrand="Digital Series",
                packaging_type="Digital file",
                product_classification="Audio",
            ),
        )
        rows = {
            key: value
            for key, value in self.conn.execute("SELECT key, value FROM app_kv").fetchall()
        }
        self.assertEqual(rows["gs1/default_contract_number"], "10070050")
        self.assertEqual(rows["gs1/default_target_market"], "Worldwide")
        self.assertEqual(rows["gs1/default_language"], "English")
        self.assertEqual(rows["gs1/default_brand"], "Orbit Label")
        self.assertEqual(rows["gs1/default_subbrand"], "Digital Series")
        self.assertEqual(rows["gs1/default_packaging_type"], "Digital file")
        self.assertEqual(rows["gs1/default_product_classification"], "Audio")

    def test_contracts_round_trip_through_app_kv(self):
        saved = self.service.set_contracts(
            (
                GS1ContractEntry(
                    contract_number="10064976",
                    product="GS1 codepakket 10",
                    company_number="87208927246",
                    start_number="8720892724601",
                    end_number="8720892724694",
                    status="Actief",
                ),
                GS1ContractEntry(
                    contract_number="10070050",
                    product="GS1 codepakket 100",
                    company_number="8721398389",
                    start_number="8721398389004",
                    end_number="8721398389998",
                    status="Actief",
                ),
            ),
            source_path="/tmp/contracts.csv",
        )

        self.assertEqual(len(saved), 2)
        self.assertEqual(self.service.load_contracts_csv_path(), "/tmp/contracts.csv")
        self.assertEqual(
            [entry.contract_number for entry in self.service.load_contracts()],
            ["10064976", "10070050"],
        )

    def test_export_stored_contracts_preserves_imported_csv_bytes(self):
        entries = (
            GS1ContractEntry(
                contract_number="10064976",
                product="GS1 codepakket 10",
                company_number="87208927246",
                start_number="8720892724601",
                end_number="8720892724694",
                status="Actief",
            ),
        )
        csv_path = Path(self.tmpdir.name) / "contracts-export.csv"
        original_bytes = (
            b"Contract Number,Product,Company Number,Start Number,End Number,Status\r\n"
            b"10064976,GS1 codepakket 10,87208927246,8720892724601,8720892724694,Actief\r\n"
        )
        csv_path.write_bytes(original_bytes)

        self.service.set_contracts(entries, source_path=str(csv_path))

        exported_path = Path(self.tmpdir.name) / "stored-contracts.csv"
        saved_path = self.service.export_stored_contracts(exported_path)

        self.assertEqual(saved_path, exported_path)
        self.assertEqual(exported_path.read_bytes(), original_bytes)

    def test_export_stored_contracts_falls_back_to_canonical_csv(self):
        self.service.set_contracts(
            (
                GS1ContractEntry(
                    contract_number="10070050",
                    product="GS1 codepakket 100",
                    company_number="8721398389",
                    start_number="8721398389004",
                    end_number="8721398389998",
                    status="Actief",
                ),
            )
        )

        exported_path = Path(self.tmpdir.name) / "canonical-contracts.csv"
        self.service.export_stored_contracts(exported_path)
        exported_text = exported_path.read_text(encoding="utf-8-sig")

        self.assertIn("Contract Number,Product,Company Number", exported_text)
        self.assertIn("10070050,GS1 codepakket 100,8721398389", exported_text)

    def test_template_workbook_round_trips_through_profile_database(self):
        template_path = Path(self.tmpdir.name) / "official-gs1-template.xlsx"
        build_template(template_path)

        stored = self.service.import_template_from_path(template_path)

        self.assertTrue(self.service.has_stored_template())
        self.assertEqual(stored.filename, "official-gs1-template.xlsx")
        self.assertEqual(stored.source_path, str(template_path))
        self.assertTrue(stored.stored_in_database)
        self.assertEqual(self.service.load_template_path(), "")
        exported_path = Path(self.tmpdir.name) / "exported-template.xlsx"
        saved_path = self.service.export_stored_template(exported_path)
        self.assertEqual(saved_path, exported_path)
        self.assertEqual(exported_path.read_bytes(), template_path.read_bytes())

    def test_template_workbook_can_be_stored_as_managed_file_and_converted_back(self):
        template_path = Path(self.tmpdir.name) / "managed-gs1-template.xlsx"
        build_template(template_path)

        stored = self.service.import_template_from_path(template_path, storage_mode="managed_file")

        self.assertEqual(stored.storage_mode, "managed_file")
        self.assertFalse(stored.stored_in_database)
        self.assertTrue(stored.managed_file_path.startswith("gs1_templates/"))
        self.assertEqual(self.service.load_stored_template_bytes(), template_path.read_bytes())

        converted = self.service.convert_template_storage_mode("database")

        self.assertTrue(converted.stored_in_database)
        self.assertEqual(converted.storage_mode, "database")
        self.assertEqual(self.service.load_stored_template_bytes(), template_path.read_bytes())

    def test_explicit_data_root_overrides_settings_file_parent_for_managed_templates(self):
        explicit_root = Path(self.tmpdir.name) / "explicit-data-root"
        service = GS1SettingsService(self.conn, self.settings, data_root=explicit_root)
        template_path = Path(self.tmpdir.name) / "explicit-managed-template.xlsx"
        build_template(template_path)

        stored = service.import_template_from_path(template_path, storage_mode="managed_file")

        self.assertTrue(stored.managed_file_path.startswith("gs1_templates/"))
        managed_path = explicit_root / stored.managed_file_path
        self.assertTrue(managed_path.exists())
        self.assertEqual(service.data_root, explicit_root.resolve())


if __name__ == "__main__":
    unittest.main()

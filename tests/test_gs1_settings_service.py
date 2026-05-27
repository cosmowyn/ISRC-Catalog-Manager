import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from PySide6.QtCore import QSettings

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.services import (
    GS1ContractEntry,
    GS1ProfileDefaults,
    GS1SettingsService,
    GS1TemplateVerificationError,
)


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

    def test_template_validation_bytes_legacy_asset_and_clear_paths(self):
        missing_template = Path(self.tmpdir.name) / "missing.xlsx"
        with self.assertRaisesRegex(GS1TemplateVerificationError, "not found"):
            self.service.import_template_from_path(missing_template)

        unsupported_template = Path(self.tmpdir.name) / "template.txt"
        unsupported_template.write_text("not a workbook", encoding="utf-8")
        with self.assertRaisesRegex(GS1TemplateVerificationError, "supported Excel"):
            self.service.import_template_from_path(unsupported_template)

        with self.assertRaisesRegex(GS1TemplateVerificationError, "empty"):
            self.service.import_template_from_bytes(b"", filename="empty.xlsx")
        with self.assertRaisesRegex(GS1TemplateVerificationError, "must be an"):
            self.service.import_template_from_bytes(b"raw", filename="template.txt")

        legacy_template = Path(self.tmpdir.name) / "legacy-template.xlsx"
        build_template(legacy_template)
        self.service.set_template_path(str(legacy_template))
        legacy_asset = self.service.load_template_asset()
        self.assertIsNotNone(legacy_asset)
        assert legacy_asset is not None
        self.assertEqual(legacy_asset.filename, "legacy-template.xlsx")
        self.assertEqual(legacy_asset.storage_mode, STORAGE_MODE_MANAGED_FILE)

        missing_legacy = Path(self.tmpdir.name) / "missing-legacy.xlsx"
        self.service.set_template_path(str(missing_legacy))
        missing_asset = self.service.load_template_asset()
        self.assertIsNotNone(missing_asset)
        assert missing_asset is not None
        self.assertEqual(missing_asset.filename, "missing-legacy.xlsx")
        self.assertEqual(missing_asset.storage_mode, STORAGE_MODE_DATABASE)

        stored = self.service.import_template_from_bytes(
            legacy_template.read_bytes(),
            filename="from-bytes.xlsx",
            storage_mode=STORAGE_MODE_DATABASE,
        )
        self.assertEqual(stored.storage_mode, STORAGE_MODE_DATABASE)
        self.assertEqual(
            self.service.convert_template_storage_mode(STORAGE_MODE_DATABASE),
            stored,
        )
        self.service.clear_stored_template()
        self.assertFalse(self.service.has_stored_template())
        with self.assertRaisesRegex(GS1TemplateVerificationError, "No official GS1 workbook"):
            self.service.export_stored_template(Path(self.tmpdir.name) / "missing-out.xlsx")

    def test_managed_template_storage_requires_a_configured_data_root(self):
        memory_settings = QSettings()
        service = GS1SettingsService(self.conn, memory_settings, data_root=None)

        with self.assertRaisesRegex(GS1TemplateVerificationError, "not configured"):
            service.import_template_from_bytes(
                b"workbook",
                filename="official.xlsx",
                storage_mode=STORAGE_MODE_MANAGED_FILE,
            )

        self.service.import_template_from_bytes(
            b"workbook",
            filename="official.xlsx",
            storage_mode=STORAGE_MODE_DATABASE,
        )
        no_root_service = GS1SettingsService(self.conn, memory_settings, data_root=None)
        with self.assertRaisesRegex(GS1TemplateVerificationError, "not configured"):
            no_root_service.convert_template_storage_mode(STORAGE_MODE_MANAGED_FILE)

    def test_template_storage_schema_and_missing_asset_edges(self):
        legacy_conn = make_settings_conn()
        legacy_conn.execute(
            """
            CREATE TABLE GS1TemplateStorage (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                filename TEXT NOT NULL,
                source_path TEXT,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        try:
            GS1SettingsService(legacy_conn, self.settings)
            columns = {
                row[1]
                for row in legacy_conn.execute("PRAGMA table_info(GS1TemplateStorage)").fetchall()
            }
            self.assertIn("managed_file_path", columns)
            self.assertIn("storage_mode", columns)
            self.assertIn("workbook_blob", columns)
        finally:
            legacy_conn.close()

        with self.assertRaisesRegex(GS1TemplateVerificationError, "No official GS1 workbook"):
            self.service.convert_template_storage_mode(STORAGE_MODE_DATABASE)

        self.conn.execute(
            """
            INSERT INTO GS1TemplateStorage(
                id, filename, source_path, storage_mode, workbook_blob, mime_type, size_bytes
            )
            VALUES (1, 'missing.xlsx', '', 'database', NULL, '', 0)
            """
        )
        self.assertIsNone(self.service.load_stored_template_bytes())
        with self.assertRaisesRegex(GS1TemplateVerificationError, "missing or unreadable"):
            self.service.convert_template_storage_mode(STORAGE_MODE_MANAGED_FILE)

    def test_data_root_and_legacy_template_stat_failures_are_tolerated(self):
        class BadSettings:
            def fileName(self):
                raise RuntimeError("settings unavailable")

        self.assertIsNone(GS1SettingsService(self.conn, BadSettings()).data_root)

        legacy_template = Path(self.tmpdir.name) / "stat-error-template.xlsx"
        self.service.set_template_path(str(legacy_template))
        with (
            mock.patch("isrc_manager.services.gs1_settings.Path.exists", return_value=True),
            mock.patch("isrc_manager.services.gs1_settings.Path.stat", side_effect=OSError),
        ):
            asset = self.service.load_template_asset()
        self.assertEqual(asset.size_bytes, 0)

    def test_contract_loading_filename_clear_and_missing_export_edges(self):
        self.conn.execute(
            "INSERT INTO app_kv(key, value) VALUES(?, ?)",
            (GS1SettingsService.CONTRACTS_JSON_KEY, "{bad json"),
        )
        self.assertEqual(self.service.load_contracts(), ())

        self.assertEqual(self.service.load_stored_contracts_filename(), "")
        with self.assertRaisesRegex(GS1TemplateVerificationError, "No GTIN contracts CSV"):
            self.service.export_stored_contracts(Path(self.tmpdir.name) / "missing.csv")

        source_path = Path(self.tmpdir.name) / "source-contracts.csv"
        source_path.write_text("Contract Number\n1001\n", encoding="utf-8")
        self.service.set_contracts(
            [
                GS1ContractEntry(
                    contract_number="1001",
                    product="",
                    company_number="",
                    start_number="",
                    end_number="",
                ),
                GS1ContractEntry(contract_number=""),
            ],
            source_path=str(source_path),
            source_filename="",
        )
        self.assertEqual(self.service.load_stored_contracts_filename(), "source-contracts.csv")
        self.assertEqual(self.service.load_stored_contracts_bytes(), source_path.read_bytes())

        self.service.clear_contracts()
        self.assertEqual(self.service.load_contracts(), ())
        self.assertEqual(self.service.load_contracts_csv_path(), "")

    def test_contract_bytes_prefer_explicit_sources_and_legacy_fallbacks(self):
        explicit_bytes = b"Contract Number\n9001\n"
        explicit_path = Path(self.tmpdir.name) / "explicit-contracts.csv"
        explicit_path.write_bytes(b"Contract Number\n9002\n")

        self.assertEqual(
            self.service._resolve_contract_bytes(source_bytes=explicit_bytes),
            explicit_bytes,
        )
        self.assertEqual(
            self.service._resolve_contract_bytes(source_path=str(explicit_path)),
            explicit_path.read_bytes(),
        )
        self.assertEqual(
            self.service._contracts_filename(source_filename="named.csv"),
            "named.csv",
        )
        self.assertEqual(
            self.service._contracts_filename(source_path=str(explicit_path)),
            "explicit-contracts.csv",
        )

        legacy_path = Path(self.tmpdir.name) / "legacy-contracts.csv"
        legacy_path.write_bytes(b"Contract Number\n9003\n")
        self.conn.execute(
            "INSERT INTO app_kv(key, value) VALUES(?, ?)",
            (GS1SettingsService.CONTRACTS_CSV_PATH_KEY, str(legacy_path)),
        )
        self.assertEqual(self.service.load_stored_contracts_filename(), "legacy-contracts.csv")
        self.assertEqual(self.service.load_stored_contracts_bytes(), legacy_path.read_bytes())


if __name__ == "__main__":
    unittest.main()

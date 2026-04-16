import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook
from PySide6.QtCore import QSettings

from isrc_manager.blob_icons import default_blob_icon_settings
from isrc_manager.services import (
    ApplicationSettingsTransferService,
    GS1ContractEntry,
    GS1ProfileDefaults,
    GS1SettingsService,
    GS1TemplateAsset,
)
from isrc_manager.starter_themes import starter_theme_library


def make_conn():
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


def build_current_values(*, icon_path: str, custom_theme_name: str = "Migrated Theme"):
    theme_library = starter_theme_library()
    theme_library[custom_theme_name] = {
        "accent": "#118AB2",
        "button_radius": 12,
        "selected_name": "",
        "custom_qss": "",
    }
    return {
        "window_title": "Migrated Catalog",
        "icon_path": icon_path,
        "artist_code": "42",
        "auto_snapshot_enabled": True,
        "auto_snapshot_interval_minutes": 45,
        "history_retention_mode": "balanced",
        "history_auto_cleanup_enabled": True,
        "history_storage_budget_mb": 2048,
        "history_auto_snapshot_keep_latest": 25,
        "history_prune_pre_restore_copies_after_days": 14,
        "isrc_prefix": "NLABC",
        "sena_number": "SENA-01",
        "btw_number": "BTW-02",
        "buma_relatie_nummer": "REL-03",
        "buma_ipi": "IPI-04",
        "theme_settings": {
            "font_family": "Helvetica Neue",
            "font_size": 12,
            "selected_name": custom_theme_name,
            "custom_qss": "QLabel { color: #123456; }",
        },
        "theme_library": theme_library,
        "blob_icon_settings": default_blob_icon_settings(),
        "gs1_active_contract_number": "10070050",
        "gs1_target_market": "Worldwide",
        "gs1_language": "English",
        "gs1_brand": "Cosmowyn",
        "gs1_subbrand": "Records",
        "gs1_packaging_type": "Digital file",
        "gs1_product_classification": "Audio",
    }


class SettingsTransferServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.source_conn = make_conn()
        self.source_settings = QSettings(str(self.root / "source.ini"), QSettings.IniFormat)
        self.source_settings.setFallbacksEnabled(False)
        self.source_gs1 = GS1SettingsService(
            self.source_conn,
            self.source_settings,
            data_root=self.root / "source-data",
        )

    def tearDown(self):
        self.source_settings.clear()
        self.source_conn.close()
        self.tmpdir.cleanup()

    def test_export_bundle_writes_settings_json_and_attachments(self):
        template_path = self.root / "official-gs1-template.xlsx"
        build_template(template_path)
        self.source_gs1.import_template_from_path(template_path)
        self.source_gs1.set_profile_defaults(
            GS1ProfileDefaults(
                contract_number="10070050",
                target_market="Worldwide",
                language="English",
                brand="Cosmowyn",
                subbrand="Records",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )
        contracts_path = self.root / "contracts.csv"
        contracts_bytes = (
            b"Contract Number,Product,Company Number,Start Number,End Number,Status\r\n"
            b"10070050,GS1 codepakket 100,8721398389,8721398389004,8721398389998,Actief\r\n"
        )
        contracts_path.write_bytes(contracts_bytes)
        self.source_gs1.set_contracts(
            (
                GS1ContractEntry(
                    contract_number="10070050",
                    product="GS1 codepakket 100",
                    company_number="8721398389",
                    start_number="8721398389004",
                    end_number="8721398389998",
                    status="Actief",
                ),
            ),
            source_path=str(contracts_path),
        )
        icon_path = self.root / "app-icon.ico"
        icon_path.write_bytes(b"ICON")
        transfer = ApplicationSettingsTransferService(
            gs1_settings_service=self.source_gs1,
            data_root=self.root / "export-data",
        )

        destination = self.root / "settings-export.zip"
        saved_path = transfer.export_bundle(
            destination,
            current_values=build_current_values(icon_path=str(icon_path)),
            app_version="3.1.1",
        )

        self.assertEqual(saved_path, destination)
        with ZipFile(destination) as archive:
            names = set(archive.namelist())
            self.assertIn("settings.json", names)
            self.assertIn("general/icon/app-icon.ico", names)
            self.assertIn("gs1/contracts/contracts.csv", names)
            self.assertIn("gs1/template/official-gs1-template.xlsx", names)
            payload = json.loads(archive.read("settings.json").decode("utf-8"))

        self.assertEqual(payload["bundle_format"], "isrc-catalog-manager-settings")
        self.assertEqual(payload["bundle_version"], 1)
        self.assertEqual(payload["general"]["artist_code"], "42")
        self.assertTrue(payload["gs1"]["template"]["present"])
        self.assertTrue(payload["gs1"]["contracts"]["present"])
        self.assertIn("Migrated Theme", payload["theme"]["custom_theme_library"])
        self.assertNotIn("Apple Light", payload["theme"]["custom_theme_library"])

    def test_prepare_import_restores_portable_values_and_attachments(self):
        template_path = self.root / "official-gs1-template.xlsx"
        build_template(template_path)
        template_bytes = template_path.read_bytes()
        self.source_gs1.import_template_from_path(template_path, storage_mode="managed_file")
        self.source_gs1.set_profile_defaults(
            GS1ProfileDefaults(
                contract_number="10070050",
                target_market="Worldwide",
                language="English",
                brand="Cosmowyn",
                subbrand="Records",
                packaging_type="Digital file",
                product_classification="Audio",
            )
        )
        contracts_path = self.root / "contracts.csv"
        contracts_bytes = (
            b"Contract Number,Product,Company Number,Start Number,End Number,Status\r\n"
            b"10070050,GS1 codepakket 100,8721398389,8721398389004,8721398389998,Actief\r\n"
        )
        contracts_path.write_bytes(contracts_bytes)
        self.source_gs1.set_contracts(
            (
                GS1ContractEntry(
                    contract_number="10070050",
                    product="GS1 codepakket 100",
                    company_number="8721398389",
                    start_number="8721398389004",
                    end_number="8721398389998",
                    status="Actief",
                ),
            ),
            source_path=str(contracts_path),
        )
        icon_path = self.root / "app-icon.ico"
        icon_path.write_bytes(b"ICON")
        export_service = ApplicationSettingsTransferService(
            gs1_settings_service=self.source_gs1,
            data_root=self.root / "export-data",
        )
        archive_path = export_service.export_bundle(
            self.root / "settings-export.zip",
            current_values=build_current_values(icon_path=str(icon_path)),
            app_version="3.1.1",
        )

        target_transfer = ApplicationSettingsTransferService(
            gs1_settings_service=None,
            data_root=self.root / "import-data",
        )
        current_values = build_current_values(icon_path="")
        current_values["window_title"] = ""
        current_values["theme_library"] = starter_theme_library()
        current_values["theme_settings"] = {}
        current_values["blob_icon_settings"] = default_blob_icon_settings()
        current_values["gs1_contract_entries"] = ()
        current_values["gs1_contracts_csv_path"] = ""
        current_values["gs1_template_asset"] = None

        result = target_transfer.prepare_import(
            archive_path,
            current_values=current_values,
        )

        self.assertEqual(result.values["window_title"], "Migrated Catalog")
        self.assertTrue(Path(str(result.values["icon_path"])).exists())
        self.assertIn("Migrated Theme", result.values["theme_library"])
        self.assertEqual(result.values["gs1_template_import_bytes"], template_bytes)
        self.assertEqual(
            result.values["gs1_template_import_filename"], "official-gs1-template.xlsx"
        )
        self.assertFalse(result.values["gs1_template_clear_existing"])
        self.assertEqual(result.values["gs1_contracts_csv_bytes"], contracts_bytes)
        self.assertEqual(result.values["gs1_contracts_csv_path"], "")
        self.assertEqual(
            [entry.contract_number for entry in result.values["gs1_contract_entries"]],
            ["10070050"],
        )

    def test_prepare_import_marks_absent_gs1_assets_for_clear(self):
        transfer = ApplicationSettingsTransferService(
            gs1_settings_service=self.source_gs1,
            data_root=self.root / "export-data",
        )
        archive_path = transfer.export_bundle(
            self.root / "settings-empty.zip",
            current_values=build_current_values(icon_path=""),
            app_version="3.1.1",
        )
        target_transfer = ApplicationSettingsTransferService(
            gs1_settings_service=None,
            data_root=self.root / "import-data",
        )
        current_values = build_current_values(icon_path="")
        current_values["gs1_template_asset"] = GS1TemplateAsset(filename="existing-template.xlsx")
        current_values["gs1_contract_entries"] = (
            GS1ContractEntry(
                contract_number="legacy",
                start_number="1",
                end_number="2",
            ),
        )
        current_values["gs1_contracts_csv_path"] = "/tmp/legacy.csv"

        result = target_transfer.prepare_import(
            archive_path,
            current_values=current_values,
        )

        self.assertTrue(result.values["gs1_template_clear_existing"])
        self.assertEqual(result.values["gs1_contract_entries"], ())
        self.assertEqual(result.values["gs1_contracts_csv_path"], "")


if __name__ == "__main__":
    unittest.main()

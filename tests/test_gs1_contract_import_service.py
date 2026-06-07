import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.services import GS1ContractImportError, GS1ContractImportService


class GS1ContractImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GS1ContractImportService()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_contracts_filters_to_gtin_contract_ranges(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Contractnummer,Product,Bedrijfsnummer,Startnummer,Eindnummer,Verlengingsdatum,Einddatum,Status,Staffel",
                    "10070049,GS1 Contribution,,,,2026-09-02,,Actief,",
                    ",GS1 codepakket 1,8720000000,8720000000001,8720000000001,2026-06-01,,Actief,",
                    "10064976,GS1 codepakket 10,87208927246,8720892724601,8720892724694,2026-06-01,,Actief,",
                    "10070050,GS1 codepakket 100,8721398389,8721398389004,8721398389998,2026-09-02,,Actief,",
                ]
            ),
            encoding="utf-8",
        )

        entries = self.service.load_contracts(csv_path)

        self.assertEqual([entry.contract_number for entry in entries], ["10064976", "10070050"])
        self.assertTrue(all(entry.start_number and entry.end_number for entry in entries))
        self.assertTrue(all(entry.is_active for entry in entries))

    def test_load_contracts_requires_existing_csv_file(self):
        with self.assertRaisesRegex(GS1ContractImportError, "not found"):
            self.service.load_contracts(self.root / "missing.csv")

    def test_load_contracts_requires_csv_suffix(self):
        contract_path = self.root / "contracts.txt"
        contract_path.write_text("Contractnummer,Startnummer,Eindnummer\n", encoding="utf-8")

        with self.assertRaisesRegex(GS1ContractImportError, r"\.csv"):
            self.service.load_contracts(contract_path)

    def test_load_contracts_rejects_empty_csv(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text("", encoding="utf-8")

        with self.assertRaisesRegex(GS1ContractImportError, "headers"):
            self.service.load_contracts(csv_path)

    def test_load_contracts_rejects_missing_contract_number_header(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Product,Startnummer,Eindnummer",
                    "GS1 codepakket 10,8720892724601,8720892724694",
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(GS1ContractImportError, "contract-number"):
            self.service.load_contracts(csv_path)

    def test_load_contracts_rejects_csv_without_gtin_ranges(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Contractnummer,Product,Startnummer,Eindnummer,Status",
                    ",GS1 codepakket 1,8720892724601,8720892724601,Actief",
                    "10070049,GS1 Contribution,,,Actief",
                    "10070050,GS1 codepakket ABC,not-a-start,not-an-end,Actief",
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaises(GS1ContractImportError):
            self.service.load_contracts(csv_path)

    def test_load_contracts_wraps_decode_errors(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_bytes(b"\xff\xfe\xff")

        with self.assertRaisesRegex(GS1ContractImportError, "decoded"):
            self.service.load_contracts(csv_path)

    def test_load_contracts_wraps_read_errors(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text("Contractnummer,Startnummer,Eindnummer\n", encoding="utf-8")

        with mock.patch(
            "isrc_manager.services.gs1_contracts.Path.open", side_effect=OSError("locked")
        ):
            with self.assertRaisesRegex(GS1ContractImportError, "could not be read"):
                self.service.load_contracts(csv_path)

    def test_load_contracts_sorts_active_numeric_then_text_contracts(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Contractnummer,Product,Startnummer,Eindnummer,Status",
                    "ABC,GS1 codepakket text,8720000000101,8720000000109,Actief",
                    "10070050,GS1 codepakket expired,8720000000201,8720000000209,Expired",
                    "10064976,GS1 codepakket active,8720000000301,8720000000309,Actief",
                ]
            ),
            encoding="utf-8",
        )

        entries = self.service.load_contracts(csv_path)

        self.assertEqual(
            [entry.contract_number for entry in entries], ["10064976", "ABC", "10070050"]
        )
        self.assertEqual(entries[1].product, "GS1 codepakket text")


if __name__ == "__main__":
    unittest.main()

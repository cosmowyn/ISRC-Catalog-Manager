import tempfile
import unittest
from pathlib import Path

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

    def test_load_contracts_rejects_csv_without_gtin_ranges(self):
        csv_path = self.root / "contracts.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "Contractnummer,Product,Status",
                    "10070049,GS1 Contribution,Actief",
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaises(GS1ContractImportError):
            self.service.load_contracts(csv_path)


if __name__ == "__main__":
    unittest.main()

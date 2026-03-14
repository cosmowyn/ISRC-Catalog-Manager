import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from isrc_manager.services import GS1TemplateVerificationError, GS1TemplateVerificationService
from isrc_manager.services.gs1_mapping import localize_export_value, resolve_header_row


HEADERS = [
    "GS1 Artikelcode (GTIN)",
    "Status",
    "Productclassificatie",
    "Gaat naar de consument",
    "Verpakkings type",
    "Landen of Regio's",
    "Productomschrijving (max 300 tekens)",
    "Taal",
    "Merk",
    "Submerk",
    "Aantal",
    "Eenheid",
    "Afbeelding (max 500 tekens)",
]


def build_verified_workbook(path: Path, *, include_placeholder_sheet: bool = True):
    workbook = Workbook()
    reference_sheet = workbook.active
    reference_sheet.title = "Reference Data"
    reference_sheet["A1"] = "Packaging"
    instruction_sheet = workbook.create_sheet("Instructions")
    instruction_sheet["A1"] = "GS1 article code (GTIN)"
    instruction_sheet["A2"] = "Upload the workbook after filling the fields."
    if include_placeholder_sheet:
        placeholder_sheet = workbook.create_sheet("{ContractNr}")
        placeholder_sheet.append(HEADERS)
    target_sheet = workbook.create_sheet("10070050")
    target_sheet.append(HEADERS)
    workbook.save(path)


class GS1HeaderMappingTests(unittest.TestCase):
    def test_resolve_header_row_maps_canonical_fields(self):
        column_map, matched_headers, total_score = resolve_header_row(HEADERS)

        self.assertEqual(column_map["gtin_request_number"], 1)
        self.assertEqual(column_map["consumer_unit_flag"], 4)
        self.assertEqual(column_map["product_description"], 7)
        self.assertEqual(column_map["image_url"], 13)
        self.assertEqual(matched_headers["brand"], "Merk")
        self.assertGreater(total_score, 20.0)

    def test_localize_export_value_handles_known_dutch_variants(self):
        self.assertEqual(localize_export_value("consumer_unit_flag", True, "nl"), "Ja")
        self.assertEqual(localize_export_value("status", "Active", "nl"), "Actief")
        self.assertEqual(localize_export_value("language", "English", "nl"), "Engels")


class GS1TemplateVerificationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GS1TemplateVerificationService()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_verify_selects_actual_contract_sheet(self):
        workbook_path = self.root / "official_template.xlsx"
        build_verified_workbook(workbook_path)

        result = self.service.verify(workbook_path)

        self.assertEqual(result.sheet_name, "10070050")
        self.assertEqual(result.header_row, 1)
        self.assertEqual(result.column_map["gtin_request_number"], 1)
        self.assertEqual(result.column_map["quantity"], 11)
        self.assertEqual(result.locale_hint, "nl")

    def test_verify_rejects_arbitrary_workbook(self):
        workbook_path = self.root / "random.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sheet1"
        sheet.append(["First Name", "Last Name", "Email"])
        workbook.save(workbook_path)

        with self.assertRaises(GS1TemplateVerificationError):
            self.service.verify(workbook_path)

    def test_verify_rejects_workbook_with_missing_required_headers(self):
        workbook_path = self.root / "missing_headers.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Products"
        sheet.append(
            [
                "GS1 Artikelcode (GTIN)",
                "Status",
                "Productclassificatie",
                "Gaat naar de consument",
                "Verpakkings type",
                "Landen of Regio's",
                "Productomschrijving (max 300 tekens)",
                "Taal",
                "Merk",
            ]
        )
        workbook.save(workbook_path)

        with self.assertRaises(GS1TemplateVerificationError):
            self.service.verify(workbook_path)


if __name__ == "__main__":
    unittest.main()

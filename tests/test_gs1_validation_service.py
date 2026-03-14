import unittest

from isrc_manager.services import GS1MetadataRecord, GS1ValidationService


class GS1ValidationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GS1ValidationService()

    def _valid_record(self):
        return GS1MetadataRecord(
            track_id=1,
            status="Concept",
            product_classification="Audio",
            consumer_unit_flag=True,
            packaging_type="Digital file",
            target_market="Worldwide",
            language="English",
            product_description="Orbit Release",
            brand="Orbit Label",
            subbrand="",
            quantity="1",
            unit="Each",
            image_url="https://example.com/cover.png",
            notes="",
            export_enabled=True,
        )

    def test_valid_record_passes(self):
        result = self.service.validate(self._valid_record())
        self.assertTrue(result.is_valid)
        self.assertEqual(result.messages(), [])

    def test_missing_required_fields_are_reported(self):
        record = self._valid_record()
        record.brand = ""
        record.product_description = ""
        result = self.service.validate(record)

        self.assertFalse(result.is_valid)
        self.assertIn("Brand is required.", result.messages())
        self.assertIn("Product Description is required.", result.messages())

    def test_length_limits_and_quantity_validation_are_enforced(self):
        record = self._valid_record()
        record.product_description = "x" * 301
        record.brand = "b" * 71
        record.subbrand = "s" * 71
        record.image_url = "https://example.com/" + ("a" * 490)
        record.quantity = "abc"

        result = self.service.validate(record)

        self.assertFalse(result.is_valid)
        messages = result.messages()
        self.assertIn("Product Description must be 300 characters or fewer.", messages)
        self.assertIn("Brand must be 70 characters or fewer.", messages)
        self.assertIn("Subbrand must be 70 characters or fewer.", messages)
        self.assertIn("Image URL must be 500 characters or fewer.", messages)
        self.assertIn("Quantity must be a positive numeric value.", messages)

    def test_export_enabled_flag_blocks_export_validation(self):
        record = self._valid_record()
        record.export_enabled = False

        result = self.service.validate(record, for_export=True)

        self.assertFalse(result.is_valid)
        self.assertIn("Export is disabled for this record.", result.messages())

    def test_contract_number_is_required_for_export(self):
        record = self._valid_record()
        record.contract_number = ""

        result = self.service.validate(record, for_export=True)

        self.assertFalse(result.is_valid)
        self.assertIn("Contract Number is required for export.", result.messages())


if __name__ == "__main__":
    unittest.main()

import unittest

from isrc_manager.constants import (
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    MAX_HISTORY_STORAGE_BUDGET_MB,
)
from isrc_manager.storage_sizes import (
    bytes_to_megabytes_floor,
    format_budget_megabytes,
    format_storage_bytes,
    megabytes_to_bytes,
    parse_history_storage_budget_mb,
    parse_storage_text_to_megabytes,
)


class StorageSizeTests(unittest.TestCase):
    def test_budget_formatting_switches_from_mb_to_gb_and_tb(self):
        self.assertEqual(format_budget_megabytes(512), "512 MB")
        self.assertEqual(format_budget_megabytes(1024), "1 GB")
        self.assertEqual(format_budget_megabytes(1536), "1.5 GB")
        self.assertEqual(format_budget_megabytes(1048576), "1 TB")

    def test_storage_text_parser_accepts_supported_units_and_decimal_styles(self):
        self.assertEqual(parse_storage_text_to_megabytes("512MB"), 512)
        self.assertEqual(parse_storage_text_to_megabytes("512 MB"), 512)
        self.assertEqual(parse_storage_text_to_megabytes("1.5 GB"), 1536)
        self.assertEqual(parse_storage_text_to_megabytes("1,5 GB"), 1536)
        self.assertEqual(parse_storage_text_to_megabytes("1 tb"), 1048576)

    def test_storage_budget_reader_uses_default_for_invalid_and_clamps_numeric_values(self):
        self.assertEqual(
            parse_history_storage_budget_mb("bad-value"), DEFAULT_HISTORY_STORAGE_BUDGET_MB
        )
        self.assertEqual(
            parse_history_storage_budget_mb(str(MAX_HISTORY_STORAGE_BUDGET_MB + 1)),
            MAX_HISTORY_STORAGE_BUDGET_MB,
        )

    def test_byte_conversion_helpers_use_binary_units(self):
        self.assertEqual(megabytes_to_bytes(1), 1024 * 1024)
        self.assertEqual(bytes_to_megabytes_floor(5 * 1024 * 1024), 5)
        self.assertEqual(format_storage_bytes(512), "512 B")
        self.assertEqual(format_storage_bytes(1024 * 1024), "1 MB")
        self.assertEqual(format_storage_bytes(1536 * 1024 * 1024), "1.5 GB")


if __name__ == "__main__":
    unittest.main()

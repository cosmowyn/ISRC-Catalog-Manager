from __future__ import annotations

import unittest
from datetime import date, datetime

from isrc_manager.contract_templates.formatting import (
    DEFAULT_MANUAL_DATE_FORMAT,
    format_manual_date_value,
    normalize_manual_date_format,
    parse_manual_date_value,
)


class ContractTemplateFormattingUnitTests(unittest.TestCase):
    def test_normalize_manual_date_format_uses_default_for_blank_values(self):
        self.assertEqual(normalize_manual_date_format(None), DEFAULT_MANUAL_DATE_FORMAT)
        self.assertEqual(normalize_manual_date_format("   "), DEFAULT_MANUAL_DATE_FORMAT)
        self.assertEqual(normalize_manual_date_format(" yyyy-mm-dd "), "yyyy-mm-dd")

    def test_parse_manual_date_value_accepts_supported_date_inputs(self):
        cases = (
            (datetime(2026, 6, 4, 10, 30, 0), date(2026, 6, 4)),
            (date(2026, 6, 4), date(2026, 6, 4)),
            ("2026-06-04", date(2026, 6, 4)),
            ("2026/06/04", date(2026, 6, 4)),
            ("04.06.2026", date(2026, 6, 4)),
            ("04/06/2026", date(2026, 6, 4)),
            ("2026-06-04T22:10:00", date(2026, 6, 4)),
        )

        for raw_value, expected in cases:
            with self.subTest(raw_value=raw_value):
                self.assertEqual(parse_manual_date_value(raw_value), expected)

    def test_parse_manual_date_value_returns_none_for_empty_or_invalid_values(self):
        for raw_value in (None, "", "not-a-date", "2026-99-99"):
            with self.subTest(raw_value=raw_value):
                self.assertIsNone(parse_manual_date_value(raw_value))

    def test_format_manual_date_value_renders_supported_tokens(self):
        cases = (
            (None, "04.Jun.2026"),
            ("d.mmm.yy", "4.Jun.26"),
            ("yyyy-mm-dd", "2026-06-04"),
            ("dd/mm/yyyy", "04/06/2026"),
            ("d mmmm yyyy", "4 June 2026"),
            ("m/d/yy", "6/4/26"),
            ("prefix dd mmm yyyy suffix", "prefix 04 Jun 2026 suffix"),
        )

        for format_code, expected in cases:
            with self.subTest(format_code=format_code):
                self.assertEqual(format_manual_date_value(date(2026, 6, 4), format_code), expected)

    def test_format_manual_date_value_preserves_unparseable_values(self):
        cases = (
            (None, ""),
            ("", ""),
            ("not-a-date", "not-a-date"),
            (0, ""),
        )

        for raw_value, expected in cases:
            with self.subTest(raw_value=raw_value):
                self.assertEqual(format_manual_date_value(raw_value, "yyyy-mm-dd"), expected)

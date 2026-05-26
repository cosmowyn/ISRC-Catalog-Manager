import unittest

from isrc_manager.contract_templates import (
    InvalidPlaceholderError,
    dedupe_placeholders,
    extract_placeholders,
    parse_placeholder,
)


class ContractTemplateParserTests(unittest.TestCase):
    def test_valid_db_and_manual_tokens_parse_successfully(self):
        db_token = parse_placeholder("{{DB.Track.Track-Title}}")
        manual_token = parse_placeholder("{{manual.license_date}}")

        self.assertEqual(db_token.binding_kind, "db")
        self.assertEqual(db_token.namespace, "track")
        self.assertEqual(db_token.key, "track_title")
        self.assertEqual(db_token.canonical_symbol, "{{db.track.track_title}}")
        self.assertEqual(manual_token.binding_kind, "manual")
        self.assertIsNone(manual_token.namespace)
        self.assertEqual(manual_token.key, "license_date")
        self.assertEqual(manual_token.canonical_symbol, "{{manual.license_date}}")

    def test_repeated_identical_tokens_dedupe_correctly(self):
        occurrences = extract_placeholders(
            "A {{db.track.track_title}} B {{db.track.track_title}} C {{manual.license_date}}"
        )
        deduped = dedupe_placeholders(occurrences)

        self.assertEqual(len(occurrences), 3)
        self.assertEqual(
            [item.canonical_symbol for item in deduped],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )

    def test_single_braces_remain_literal(self):
        occurrences = extract_placeholders(
            "{db.track.track_title} and {{db.track.track_title}} and {manual.license_date}"
        )

        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].token.canonical_symbol, "{{db.track.track_title}}")

    def test_malformed_tokens_are_rejected(self):
        for raw in (
            "{{track_title}}",
            "{{track.track_title}}",
            "{{db.track}}",
            "{{db.track.track title}}",
            "{{ db.track.track_title }}",
            "{{manual.}}",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidPlaceholderError):
                    parse_placeholder(raw)

    def test_nested_tokens_are_rejected(self):
        with self.assertRaises(InvalidPlaceholderError):
            parse_placeholder("{{db.track.{{track_title}}}}")

        self.assertEqual(
            extract_placeholders("X {{db.track.{{track_title}}}} Y"),
            (),
        )

    def test_custom_canonical_form_requires_cf_id(self):
        valid = parse_placeholder("{{db.custom.cf_12}}")
        self.assertEqual(valid.canonical_symbol, "{{db.custom.cf_12}}")

        for raw in ("{{db.custom.custom_12}}", "{{db.custom.cf_test}}", "{{db.custom.12}}"):
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidPlaceholderError):
                    parse_placeholder(raw)

    def test_indexed_suffix_supported_for_multiple_symbol_kinds(self):
        manual_indexed = parse_placeholder("{{manual.version.indexed}}")
        typed_manual_indexed = parse_placeholder("{{manual.explicit$bool[yes;no;maybe].indexed}}")
        current_indexed = parse_placeholder("{{current.year.indexed}}")
        page_indexed = parse_placeholder("{{page.index.indexed}}")
        custom_indexed = parse_placeholder("{{custom.index.indexed}}")
        duplicate_indexed = parse_placeholder("{{duplicate.number.indexed}}")
        db_indexed = parse_placeholder("{{db.track.track_title.indexed}}")

        self.assertEqual(manual_indexed.binding_kind, "manual")
        self.assertTrue(manual_indexed.indexed)
        self.assertEqual(manual_indexed.canonical_symbol, "{{manual.version.indexed}}")

        self.assertEqual(typed_manual_indexed.binding_kind, "manual")
        self.assertEqual(typed_manual_indexed.key, "explicit")
        self.assertTrue(typed_manual_indexed.indexed)
        self.assertEqual(typed_manual_indexed.manual_type, "bool")
        self.assertEqual(typed_manual_indexed.manual_options, ("yes", "no", "maybe"))
        self.assertEqual(
            typed_manual_indexed.canonical_symbol,
            "{{manual.explicit$bool[yes;no;maybe].indexed}}",
        )

        self.assertEqual(current_indexed.binding_kind, "current")
        self.assertTrue(current_indexed.indexed)
        self.assertEqual(current_indexed.canonical_symbol, "{{current.year.indexed}}")

        self.assertEqual(page_indexed.binding_kind, "page")
        self.assertTrue(page_indexed.indexed)
        self.assertEqual(page_indexed.canonical_symbol, "{{page.index.indexed}}")

        self.assertEqual(custom_indexed.binding_kind, "custom")
        self.assertTrue(custom_indexed.indexed)
        self.assertEqual(custom_indexed.canonical_symbol, "{{custom.index.indexed}}")

        self.assertEqual(duplicate_indexed.binding_kind, "duplicate")
        self.assertTrue(duplicate_indexed.indexed)
        self.assertEqual(duplicate_indexed.canonical_symbol, "{{duplicate.number.indexed}}")

        self.assertEqual(db_indexed.binding_kind, "db")
        self.assertTrue(db_indexed.indexed)
        self.assertEqual(db_indexed.canonical_symbol, "{{db.track.track_title.indexed}}")


if __name__ == "__main__":
    unittest.main()

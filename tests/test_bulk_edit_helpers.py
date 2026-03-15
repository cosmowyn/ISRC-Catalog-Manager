import unittest

from isrc_manager.services.bulk_edit import MIXED_VALUE, shared_bulk_value, should_apply_bulk_change


class BulkEditHelperTests(unittest.TestCase):
    def test_shared_bulk_value_returns_common_value_when_all_match(self):
        self.assertEqual(shared_bulk_value(["Pop", "Pop", "Pop"]), "Pop")

    def test_shared_bulk_value_marks_mixed_values(self):
        self.assertIs(shared_bulk_value(["Pop", "Rock"]), MIXED_VALUE)

    def test_should_apply_bulk_change_requires_user_modification(self):
        self.assertFalse(
            should_apply_bulk_change(
                mixed=True,
                modified=False,
                initial_value=None,
                final_value="Electronic",
            )
        )

    def test_should_apply_bulk_change_updates_mixed_fields_once_edited(self):
        self.assertTrue(
            should_apply_bulk_change(
                mixed=True,
                modified=True,
                initial_value=None,
                final_value="Electronic",
            )
        )

    def test_should_apply_bulk_change_skips_unchanged_common_values(self):
        self.assertFalse(
            should_apply_bulk_change(
                mixed=False,
                modified=True,
                initial_value="Pop",
                final_value="Pop",
            )
        )

    def test_should_apply_bulk_change_allows_clearing_common_values(self):
        self.assertTrue(
            should_apply_bulk_change(
                mixed=False,
                modified=True,
                initial_value="Pop",
                final_value="",
            )
        )


if __name__ == "__main__":
    unittest.main()

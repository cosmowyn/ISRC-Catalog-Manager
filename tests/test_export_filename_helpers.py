import unittest

from isrc_manager.file_storage import sanitize_export_basename


class ExportFilenameHelperTests(unittest.TestCase):
    def test_sanitize_export_basename_preserves_leading_letters(self):
        self.assertEqual(sanitize_export_basename("Album"), "Album")
        self.assertEqual(sanitize_export_basename("Track"), "Track")
        self.assertEqual(
            sanitize_export_basename("Distribution Status"),
            "Distribution Status",
        )

    def test_sanitize_export_basename_replaces_invalid_characters(self):
        self.assertEqual(
            sanitize_export_basename('Album: One/Two\\Three?*'),
            "Album_ One_Two_Three_",
        )

    def test_sanitize_export_basename_collapses_whitespace_and_has_fallback(self):
        self.assertEqual(
            sanitize_export_basename("  Album   Title.  "),
            "Album Title",
        )
        self.assertEqual(sanitize_export_basename(""), "file")


if __name__ == "__main__":
    unittest.main()

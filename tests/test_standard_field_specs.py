import unittest

from isrc_manager.domain.standard_fields import (
    default_base_headers,
    promoted_custom_fields,
    standard_field_spec_for_label,
    standard_media_specs_by_key,
)


class StandardFieldSpecTests(unittest.TestCase):
    def test_default_headers_preserve_requested_order(self):
        self.assertEqual(
            default_base_headers(),
            [
                "ID",
                "Audio File",
                "Track Title",
                "Track Length (hh:mm:ss)",
                "Album Title",
                "Album Art",
                "Artist Name",
                "Additional Artists",
                "ISRC",
                "BUMA Wnr.",
                "ISWC",
                "UPC",
                "Catalog#",
                "Entry Date",
                "Release Date",
                "Genre",
            ],
        )

    def test_promoted_fields_keep_original_semantic_types(self):
        promoted = {field["name"]: field for field in promoted_custom_fields()}
        self.assertEqual(promoted["Audio File"]["field_type"], "blob_audio")
        self.assertEqual(promoted["Album Art"]["field_type"], "blob_image")
        self.assertEqual(promoted["BUMA Wnr."]["field_type"], "text")
        self.assertEqual(promoted["Catalog#"]["field_type"], "text")

    def test_media_specs_expose_blob_types_and_storage_columns(self):
        audio_spec = standard_field_spec_for_label("Audio File")
        art_spec = standard_field_spec_for_label("Album Art")
        media_specs = standard_media_specs_by_key()

        self.assertIsNotNone(audio_spec)
        self.assertEqual(audio_spec.field_type, "blob_audio")
        self.assertEqual(audio_spec.path_column, "audio_file_path")
        self.assertEqual(media_specs["audio_file"].field_type, "blob_audio")

        self.assertIsNotNone(art_spec)
        self.assertEqual(art_spec.field_type, "blob_image")
        self.assertEqual(art_spec.path_column, "album_art_path")
        self.assertEqual(media_specs["album_art"].field_type, "blob_image")


if __name__ == "__main__":
    unittest.main()

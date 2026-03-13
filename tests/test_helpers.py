import tempfile
import unittest
from pathlib import Path

import ISRC_manager

from isrc_manager.domain.codes import (
    normalize_isrc,
    normalize_iswc,
    to_compact_isrc,
    to_iso_isrc,
    to_iso_iswc,
    valid_upc_ean,
)
from isrc_manager.domain.timecode import hms_to_seconds, parse_hms_text, seconds_to_hms
from isrc_manager.media.blob_files import _is_valid_audio_path, _is_valid_image_path, _read_blob_from_path
from isrc_manager.paths import BIN_DIR, DATA_DIR


class CodeHelperTests(unittest.TestCase):
    def test_isrc_helpers_normalize_and_format(self):
        self.assertEqual(normalize_isrc("nl-abc-25-12345"), "NLABC2512345")
        self.assertEqual(to_compact_isrc("nl-abc-25-12345"), "NLABC2512345")
        self.assertEqual(to_iso_isrc("nlabc2512345"), "NL-ABC-25-12345")

    def test_iswc_helper_formats_iso(self):
        self.assertEqual(normalize_iswc("t-123.456.789-0"), "T1234567890")
        self.assertEqual(to_iso_iswc("t1234567890"), "T-123.456.789-0")

    def test_upc_validation_accepts_12_or_13_digits(self):
        self.assertTrue(valid_upc_ean("123456789012"))
        self.assertTrue(valid_upc_ean("1234567890123"))
        self.assertFalse(valid_upc_ean("ABC123"))


class TimecodeTests(unittest.TestCase):
    def test_timecode_round_trip(self):
        self.assertEqual(seconds_to_hms(3661), "01:01:01")
        self.assertEqual(hms_to_seconds(1, 1, 1), 3661)
        self.assertEqual(parse_hms_text("01:01:01"), 3661)


class PathHelperTests(unittest.TestCase):
    def test_data_dir_uses_requested_app_name(self):
        self.assertEqual(DATA_DIR(app_name="SampleApp").name, "SampleApp")

    def test_portable_mode_uses_binary_dir(self):
        self.assertEqual(DATA_DIR(portable=True), BIN_DIR())


class BlobFileHelperTests(unittest.TestCase):
    def test_extension_based_media_validation(self):
        self.assertTrue(_is_valid_image_path("cover.png"))
        self.assertTrue(_is_valid_audio_path("preview.wav"))
        self.assertFalse(_is_valid_audio_path("cover.png"))

    def test_read_blob_from_path_returns_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob_path = Path(tmpdir) / "sample.bin"
            blob_path.write_bytes(b"abc123")
            self.assertEqual(_read_blob_from_path(str(blob_path)), b"abc123")


class EntryPointTests(unittest.TestCase):
    def test_main_entrypoint_is_exposed(self):
        self.assertTrue(callable(ISRC_manager.main))


if __name__ == "__main__":
    unittest.main()

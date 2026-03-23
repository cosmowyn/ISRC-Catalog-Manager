import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtGui import QImage

    from isrc_manager.blob_icons import (
        BlobIconSettingsService,
        blob_icon_spec_from_storage,
        compress_blob_icon_image,
        default_blob_icon_settings,
        finalize_blob_icon_spec,
        icon_from_blob_icon_spec,
        normalize_blob_icon_settings,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    BLOB_ICON_IMPORT_ERROR = exc
else:
    BLOB_ICON_IMPORT_ERROR = None


class BlobIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BLOB_ICON_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Blob icon helpers unavailable: {BLOB_ICON_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_default_settings_expose_primary_lossy_and_image_defaults(self):
        settings = default_blob_icon_settings()

        self.assertEqual(settings["audio"]["mode"], "emoji")
        self.assertEqual(settings["audio"]["emoji"], "🎵")
        self.assertEqual(settings["audio_lossy"]["mode"], "emoji")
        self.assertEqual(settings["audio_lossy"]["emoji"], "🎚️")
        self.assertEqual(settings["image"]["mode"], "emoji")
        self.assertEqual(settings["image"]["emoji"], "🖼️")

    def test_finalize_custom_image_compresses_into_inline_database_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "large-source.bmp"
            image = QImage(512, 512, QImage.Format_ARGB32)
            image.fill(0xFF33AA77)
            self.assertTrue(image.save(str(source_path), "BMP"))
            original_size = source_path.stat().st_size

            spec = finalize_blob_icon_spec(
                {"mode": "image", "image_path": str(source_path)},
                kind="image",
            )

            self.assertEqual(spec["mode"], "image")
            self.assertIn("image_png_base64", spec)
            self.assertNotIn("image_path", spec)
            decoded = base64.b64decode(spec["image_png_base64"])
            self.assertLess(len(decoded), original_size)
            self.assertLessEqual(int(spec["image_width"]), 40)
            self.assertLessEqual(int(spec["image_height"]), 40)

    def test_settings_service_round_trips_profile_blob_icon_settings(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE app_kv (key TEXT PRIMARY KEY, value TEXT)")
            service = BlobIconSettingsService(conn)

            saved = service.save_settings(
                {
                    "audio": {"mode": "system", "system_name": "SP_MediaPlay"},
                    "audio_lossy": {"mode": "emoji", "emoji": "📼"},
                    "image": {"mode": "emoji", "emoji": "📷"},
                }
            )
            loaded = service.load_settings()

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["audio"]["system_name"], "SP_MediaPlay")
            self.assertEqual(loaded["audio_lossy"]["emoji"], "📼")
            self.assertEqual(loaded["image"]["emoji"], "📷")
        finally:
            conn.close()

    def test_icon_from_spec_uses_inherit_fallback_safely(self):
        fallback = {"mode": "emoji", "emoji": "🎧"}
        icon = icon_from_blob_icon_spec(
            {"mode": "inherit"},
            kind="audio",
            fallback_spec=fallback,
            allow_inherit=True,
            size=22,
        )
        self.assertFalse(icon.isNull())

    def test_storage_parser_returns_inherit_for_empty_field_override(self):
        parsed = blob_icon_spec_from_storage(None, kind="audio", allow_inherit=True)
        self.assertEqual(parsed, {"mode": "inherit"})

    def test_normalize_settings_keeps_both_media_kinds_available(self):
        normalized = normalize_blob_icon_settings({"audio": {"mode": "emoji", "emoji": "🎶"}})

        self.assertEqual(normalized["audio"]["emoji"], "🎶")
        self.assertEqual(normalized["audio_lossy"]["emoji"], "🎚️")
        self.assertEqual(normalized["image"]["emoji"], "🖼️")

    def test_compress_blob_icon_image_rejects_missing_files(self):
        with self.assertRaises(ValueError):
            compress_blob_icon_image("/does/not/exist.png")


if __name__ == "__main__":
    unittest.main()

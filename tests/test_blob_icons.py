import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtGui import QImage

    from isrc_manager.blob_icons import (
        BlobIconEditorWidget,
        BlobIconSettingsService,
        blob_icon_spec_from_storage,
        compress_blob_icon_image,
        default_blob_icon_settings,
        default_system_icon_name,
        emoji_blob_icon_presets,
        finalize_blob_icon_spec,
        icon_from_blob_icon_spec,
        normalize_blob_icon_settings,
        recommended_emoji_blob_icon_presets,
        system_blob_icon_choices,
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

    def test_default_settings_expose_managed_and_database_audio_image_defaults(self):
        settings = default_blob_icon_settings()

        self.assertEqual(settings["audio_managed"]["mode"], "emoji")
        self.assertEqual(settings["audio_managed"]["emoji"], "🎵")
        self.assertEqual(settings["audio_database"]["mode"], "emoji")
        self.assertEqual(settings["audio_database"]["emoji"], "💽")
        self.assertEqual(settings["audio_lossy_managed"]["mode"], "emoji")
        self.assertEqual(settings["audio_lossy_managed"]["emoji"], "🎚️")
        self.assertEqual(settings["audio_lossy_database"]["mode"], "emoji")
        self.assertEqual(settings["audio_lossy_database"]["emoji"], "📼")
        self.assertEqual(settings["image_managed"]["mode"], "emoji")
        self.assertEqual(settings["image_managed"]["emoji"], "🖼️")
        self.assertEqual(settings["image_database"]["mode"], "emoji")
        self.assertEqual(settings["image_database"]["emoji"], "🗃️")

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
                    "audio_managed": {"mode": "system", "system_name": "SP_MediaPlay"},
                    "audio_database": {"mode": "emoji", "emoji": "💾"},
                    "audio_lossy_managed": {"mode": "emoji", "emoji": "🎛️"},
                    "audio_lossy_database": {"mode": "emoji", "emoji": "📼"},
                    "image_managed": {"mode": "emoji", "emoji": "📷"},
                    "image_database": {"mode": "emoji", "emoji": "🗂️"},
                }
            )
            loaded = service.load_settings()

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["audio_managed"]["system_name"], "SP_MediaPlay")
            self.assertEqual(loaded["audio_database"]["emoji"], "💾")
            self.assertEqual(loaded["audio_lossy_managed"]["emoji"], "🎛️")
            self.assertEqual(loaded["audio_lossy_database"]["emoji"], "📼")
            self.assertEqual(loaded["image_managed"]["emoji"], "📷")
            self.assertEqual(loaded["image_database"]["emoji"], "🗂️")
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

    def test_normalize_settings_backfills_all_storage_specific_media_keys(self):
        normalized = normalize_blob_icon_settings({"audio": {"mode": "emoji", "emoji": "🎶"}})

        self.assertEqual(normalized["audio_managed"]["emoji"], "🎶")
        self.assertEqual(normalized["audio_database"]["emoji"], "🎶")
        self.assertEqual(normalized["audio_lossy_managed"]["emoji"], "🎚️")
        self.assertEqual(normalized["audio_lossy_database"]["emoji"], "📼")
        self.assertEqual(normalized["image_managed"]["emoji"], "🖼️")
        self.assertEqual(normalized["image_database"]["emoji"], "🗃️")

    def test_compress_blob_icon_image_rejects_missing_files(self):
        with self.assertRaises(ValueError):
            compress_blob_icon_image("/does/not/exist.png")

    def test_emoji_picker_keeps_recommended_default_first_and_exposes_full_library(self):
        editor = BlobIconEditorWidget(kind="audio_database")
        try:
            recommended = recommended_emoji_blob_icon_presets("audio_database")
            combo_values = [
                str(editor.emoji_combo.itemData(index) or "").strip()
                for index in range(editor.emoji_combo.count())
                if str(editor.emoji_combo.itemData(index) or "").strip()
            ]

            self.assertEqual(combo_values[0], recommended[0][0])
            self.assertEqual(combo_values[0], "💽")
            self.assertIn("🖼️", combo_values)
            self.assertIn("🎨", combo_values)
        finally:
            editor.close()

    def test_system_picker_keeps_recommended_icons_first_and_exposes_full_library(self):
        editor = BlobIconEditorWidget(kind="audio_managed")
        try:
            combo_values = [
                str(editor.system_combo.itemData(index) or "").strip()
                for index in range(editor.system_combo.count())
                if str(editor.system_combo.itemData(index) or "").strip()
            ]

            self.assertEqual(combo_values[0], default_system_icon_name("audio_managed"))
            self.assertEqual(combo_values[0], "SP_MediaVolume")
            self.assertIn("SP_DesktopIcon", combo_values)
            self.assertIn("SP_ComputerIcon", combo_values)
        finally:
            editor.close()

    def test_picker_selection_supports_full_library_icons_outside_original_kind_subset(self):
        editor = BlobIconEditorWidget(kind="audio_managed")
        try:
            editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("system"))
            editor.system_combo.setCurrentIndex(editor.system_combo.findData("SP_DesktopIcon"))
            self.assertEqual(editor.current_spec()["system_name"], "SP_DesktopIcon")

            editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("emoji"))
            editor.emoji_combo.setCurrentIndex(editor.emoji_combo.findData("🖼️"))
            self.assertEqual(editor.current_spec()["emoji"], "🖼️")

            self.assertIn("🖼️", dict(emoji_blob_icon_presets("audio_managed")))
            self.assertIn(
                "SP_DesktopIcon",
                {choice.name for choice in system_blob_icon_choices("audio_managed")},
            )
        finally:
            editor.close()


if __name__ == "__main__":
    unittest.main()

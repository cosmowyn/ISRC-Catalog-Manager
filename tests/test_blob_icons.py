import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtGui import QImage

    import isrc_manager.blob_icons as blob_icons
    from isrc_manager.blob_icons import (
        BlobIconEditorWidget,
        BlobIconSettingsService,
        blob_icon_spec_from_storage,
        blob_icon_spec_to_storage,
        compress_blob_icon_image,
        decode_blob_icon_image,
        default_blob_icon_settings,
        default_system_icon_name,
        describe_blob_icon_spec,
        emoji_blob_icon_presets,
        encode_qimage_to_png_bytes,
        finalize_blob_icon_spec,
        icon_from_blob_icon_spec,
        normalize_blob_icon_settings,
        normalize_blob_icon_spec,
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

    def test_blob_icon_serialization_descriptions_and_image_decoding_edges(self):
        self.assertEqual(default_system_icon_name("unknown-kind"), "SP_FileIcon")
        self.assertEqual(normalize_blob_icon_spec("not json", kind="audio")["emoji"], "🎵")
        self.assertEqual(
            normalize_blob_icon_spec(
                {"mode": "system", "system_name": "MissingIcon"},
                kind="unknown-kind",
            ),
            {"mode": "system", "system_name": "SP_FileIcon"},
        )
        self.assertEqual(
            normalize_blob_icon_spec({"mode": "image"}, kind="image", allow_inherit=True),
            {"mode": "inherit"},
        )
        self.assertIsNone(
            blob_icon_spec_to_storage(
                {"mode": "inherit"},
                kind="image",
                allow_inherit=True,
            )
        )

        normalized_image = normalize_blob_icon_spec(
            {
                "mode": "image",
                "image_png_base64": "not-png",
                "image_label": " Cover ",
                "image_width": "wide",
                "image_height": "12",
            },
            kind="image",
        )
        self.assertEqual(normalized_image["image_label"], "Cover")
        self.assertNotIn("image_width", normalized_image)
        self.assertEqual(normalized_image["image_height"], 12)
        self.assertEqual(
            describe_blob_icon_spec(normalized_image, kind="image"),
            "Custom image · Cover",
        )
        height_error_image = normalize_blob_icon_spec(
            {
                "mode": "image",
                "image_path": "/tmp/cover.png",
                "image_height": "tall",
            },
            kind="image",
        )
        self.assertNotIn("image_height", height_error_image)
        self.assertTrue(decode_blob_icon_image({"mode": "emoji", "emoji": "🎵"}).isNull())
        self.assertTrue(decode_blob_icon_image(normalized_image).isNull())

        image = QImage(8, 6, QImage.Format_ARGB32)
        image.fill(0xFF112233)
        encoded = encode_qimage_to_png_bytes(image)
        decoded = decode_blob_icon_image(
            {
                "mode": "image",
                "image_png_base64": base64.b64encode(encoded).decode("ascii"),
            }
        )
        self.assertFalse(decoded.isNull())
        self.assertEqual((decoded.width(), decoded.height()), (8, 6))
        scaled_icon = icon_from_blob_icon_spec(
            {
                "mode": "image",
                "image_png_base64": base64.b64encode(encoded).decode("ascii"),
            },
            kind="image",
            size=4,
        )
        self.assertFalse(scaled_icon.isNull())

        with tempfile.TemporaryDirectory() as tmpdir:
            path_image = Path(tmpdir) / "stored.png"
            self.assertTrue(image.save(str(path_image), "PNG"))
            self.assertFalse(
                decode_blob_icon_image({"mode": "image", "image_path": str(path_image)}).isNull()
            )

        inherit_description = describe_blob_icon_spec(
            {"mode": "inherit"},
            kind="audio_managed",
            allow_inherit=True,
        )
        self.assertEqual(inherit_description, "Uses global audio managed icon")

    def test_blob_icon_signal_wrappers_and_encoding_error_edges(self):
        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        owner = SimpleNamespace()
        calls = []
        noarg_signal = FakeSignal()
        args_signal = FakeSignal()

        blob_icons._connect_noarg_signal(noarg_signal, owner, lambda: calls.append("noarg"))
        blob_icons._connect_args_signal(
            args_signal,
            owner,
            lambda *args: calls.append(("args", args)),
        )
        noarg_signal.callbacks[0](True)
        args_signal.callbacks[0]("value", 3)

        self.assertEqual(calls, ["noarg", ("args", ("value", 3))])
        self.assertEqual(len(owner._isrc_signal_wrappers), 2)

        with self.assertRaises(ValueError):
            compress_blob_icon_image("")

        class ClosedBuffer:
            def __init__(self, _payload):
                pass

            def open(self, _mode):
                return False

        with mock.patch.object(blob_icons, "QBuffer", ClosedBuffer):
            with self.assertRaisesRegex(ValueError, "prepare"):
                encode_qimage_to_png_bytes(QImage(1, 1, QImage.Format_ARGB32))

        class OpenBuffer:
            def __init__(self, _payload):
                self.closed = False

            def open(self, _mode):
                return True

            def close(self):
                self.closed = True

        class UnsavableImage:
            def save(self, _buffer, _format):
                return False

        with mock.patch.object(blob_icons, "QBuffer", OpenBuffer):
            with self.assertRaisesRegex(ValueError, "encode"):
                encode_qimage_to_png_bytes(UnsavableImage())

        with mock.patch.object(blob_icons.QApplication, "instance", return_value=None):
            self.assertTrue(
                icon_from_blob_icon_spec(
                    {"mode": "system", "system_name": "SP_FileIcon"},
                    kind="image",
                    style=None,
                ).isNull()
            )

    def test_blob_icon_editor_image_current_spec_edges(self):
        image = QImage(4, 4, QImage.Format_ARGB32)
        image.fill(0xFF445566)
        encoded = base64.b64encode(encode_qimage_to_png_bytes(image)).decode("ascii")

        editor = BlobIconEditorWidget(kind="image_database", allow_inherit=True)
        try:
            editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("inherit"))
            self.assertEqual(editor.current_spec(), {"mode": "inherit"})

            editor._setting_spec = True
            editor._apply_selected_emoji_preset()
            editor._setting_spec = False
            editor.emoji_combo.setCurrentIndex(-1)
            editor._apply_selected_emoji_preset()

            editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("image"))
            editor.image_path_edit.setText("/tmp/custom-icon.png")
            self.assertEqual(
                editor.current_spec(),
                {
                    "mode": "image",
                    "image_path": "/tmp/custom-icon.png",
                    "image_label": "custom-icon.png",
                },
            )

            editor.image_path_edit.clear()
            editor.image_path_edit.setProperty("stored_png_base64", encoded)
            editor.image_path_edit.setProperty("stored_image_label", "Stored Icon")
            self.assertEqual(
                editor.current_spec(),
                {
                    "mode": "image",
                    "image_png_base64": encoded,
                    "image_label": "Stored Icon",
                },
            )

            editor.image_path_edit.setProperty("stored_image_label", "")
            self.assertEqual(
                editor.current_spec(),
                {"mode": "image", "image_png_base64": encoded},
            )

            editor.image_path_edit.setProperty("stored_png_base64", "")
            self.assertEqual(editor.current_spec(), {"mode": "inherit"})

            editor.set_spec(
                {
                    "mode": "image",
                    "image_png_base64": encoded,
                    "image_label": "Stored Icon",
                }
            )
            self.assertEqual(editor.image_path_edit.property("stored_png_base64"), encoded)
            self.assertEqual(editor.image_path_edit.property("stored_image_label"), "Stored Icon")

            editor._clear_image()
            self.assertEqual(editor.image_path_edit.text(), "")
            self.assertEqual(editor.image_path_edit.property("stored_png_base64"), "")

            with mock.patch.object(
                blob_icons.QFileDialog,
                "getOpenFileName",
                return_value=("", ""),
            ):
                editor._choose_image()

            warnings = []
            with (
                mock.patch.object(
                    blob_icons.QFileDialog,
                    "getOpenFileName",
                    return_value=("/does/not/exist.png", ""),
                ),
                mock.patch.object(
                    blob_icons.QMessageBox,
                    "warning",
                    lambda *args: warnings.append(args),
                ),
            ):
                editor._choose_image()
            self.assertEqual(warnings[-1][1], "Custom Icon")

            with tempfile.TemporaryDirectory() as tmpdir:
                chosen_path = Path(tmpdir) / "chosen.png"
                self.assertTrue(image.save(str(chosen_path), "PNG"))
                with mock.patch.object(
                    blob_icons.QFileDialog,
                    "getOpenFileName",
                    return_value=(str(chosen_path), ""),
                ):
                    editor._choose_image()
                self.assertEqual(editor.image_path_edit.text(), str(chosen_path))
                self.assertEqual(editor.image_path_edit.property("stored_png_base64"), "")
        finally:
            editor.close()

        defaulting_editor = BlobIconEditorWidget(kind="image_database")
        try:
            defaulting_editor.mode_combo.setCurrentIndex(
                defaulting_editor.mode_combo.findData("image")
            )
            self.assertEqual(
                defaulting_editor.current_spec(),
                {"mode": "emoji", "emoji": "🗃️"},
            )
        finally:
            defaulting_editor.close()


if __name__ == "__main__":
    unittest.main()

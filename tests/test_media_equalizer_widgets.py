import builtins
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QDialog

from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager.media import equalizer
except Exception as exc:  # pragma: no cover - environment-specific fallback
    EQUALIZER_IMPORT_ERROR = exc
else:
    EQUALIZER_IMPORT_ERROR = None


class MediaEqualizerWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if EQUALIZER_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"Equalizer module unavailable: {EQUALIZER_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_which_prefers_windows_fallback_candidate(self):
        with (
            mock.patch.object(equalizer.platform, "system", return_value="windows"),
            mock.patch.object(equalizer.shutil, "which", return_value=None),
            mock.patch.object(equalizer.os.path, "expandvars", lambda value: value),
            mock.patch.object(
                equalizer.os.path,
                "join",
                side_effect=lambda directory, candidate: f"{directory}\\{candidate}",
            ),
            mock.patch.object(
                equalizer.os.path,
                "exists",
                lambda path: path == r"C:\ffmpeg\bin\ffmpeg.exe",
            ),
        ):
            self.assertEqual(
                equalizer._which("ffmpeg"),
                r"C:\ffmpeg\bin\ffmpeg.exe",
            )

    def test_which_returns_none_for_unknown_binary(self):
        with (
            mock.patch.object(equalizer.platform, "system", return_value="linux"),
            mock.patch.object(equalizer.shutil, "which", return_value=None),
            mock.patch.object(equalizer.os.path, "exists", return_value=False),
        ):
            self.assertIsNone(equalizer._which("ffmpeg"))

    def test_apply_equalizer_with_soundfile_returns_false_when_dependencies_are_missing(self):
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"numpy", "soundfile", "scipy", "scipy.signal"}:
                raise ImportError("missing test dependency")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch.object(builtins, "__import__", guarded_import):
            self.assertFalse(
                equalizer._apply_equalizer_with_soundfile(
                    "missing-source.wav", "missing-target.wav", {"enabled": True}
                )
            )

    def test_curve_widget_set_audio_spectrum_drives_fade_timer(self):
        widget = equalizer.EqualizerCurveWidget()
        widget.resize(260, 110)

        widget.set_audio_spectrum([0.25, 0.5, 0.75])
        self.assertGreater(widget._audio_spectrum_opacity, 0.9)
        self.assertEqual(len(widget._audio_spectrum_values), 3)

        widget.set_audio_spectrum([0.5, 0.6, 0.7])
        self.assertEqual(len(widget._audio_spectrum_values), 3)
        self.assertLess(widget._audio_spectrum_fade_timer.interval(), 100)

        widget._audio_spectrum_opacity = 0.2
        if widget._audio_spectrum_fade_timer.isActive():
            widget._audio_spectrum_fade_timer.stop()
        widget.set_audio_spectrum([])
        self.assertTrue(widget._audio_spectrum_fade_timer.isActive())

    def test_curve_widget_fade_halts_and_clears_when_below_threshold(self):
        widget = equalizer.EqualizerCurveWidget()
        widget._audio_spectrum_values = [0.4, 0.6, 0.2]
        widget._audio_spectrum_opacity = 0.02
        if not widget._audio_spectrum_fade_timer.isActive():
            widget._audio_spectrum_fade_timer.start()

        widget._advance_audio_spectrum_fade()

        self.assertEqual(widget._audio_spectrum_opacity, 0.0)
        self.assertEqual(widget._audio_spectrum_values, [])
        self.assertFalse(widget._audio_spectrum_fade_timer.isActive())

    def test_panning_dial_event_paths(self):
        widget = equalizer.PanningDialWidget()
        widget.resize(82, 38)

        received: list[float] = []
        widget.panChanged.connect(received.append)

        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(35, 8),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        widget.mousePressEvent(press)
        self.assertEqual(len(received), 1)

        move = QMouseEvent(
            QEvent.MouseMove,
            QPointF(55, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        widget.mouseMoveEvent(move)

        dbl = QMouseEvent(
            QEvent.MouseButtonDblClick,
            QPointF(20, 18),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        widget.mouseDoubleClickEvent(dbl)
        self.assertEqual(widget.pan(), 0.0)

        right_press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 18),
            Qt.RightButton,
            Qt.RightButton,
            Qt.NoModifier,
        )
        received_count = len(received)
        widget.mousePressEvent(right_press)
        self.assertGreaterEqual(len(received), received_count)
        self.assertAlmostEqual(widget.pan(), received[-1], delta=0.0001)

        key_left = QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier)
        widget.keyPressEvent(key_left)
        key_right = QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier)
        widget.keyPressEvent(key_right)
        key_home = QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier)
        widget.keyPressEvent(key_home)
        key_other = QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier)
        widget.keyPressEvent(key_other)
        self.assertGreaterEqual(len(received), 3)

    def test_equalizer_dialog_controls_emit_updates(self):
        dialog = equalizer.EqualizerDialog(
            {
                "enabled": True,
                "gains": [1.0] + [0.0] * (len(equalizer.EQUALIZER_BANDS) - 1),
                "pan": 0.4,
            }
        )
        self.assertIsInstance(dialog.windowTitle(), str)
        self.assertIsInstance(dialog, QDialog)

        events: list[dict[str, object]] = []
        dialog.settingsChanged.connect(events.append)

        self.assertEqual(dialog._format_gain(0.0), "0 dB")
        self.assertEqual(dialog._format_gain(0.55), "+0.5 dB")

        dialog.set_settings({"enabled": False, "pan": -0.4, "gains": [0.0] * 8}, emit=True)
        self.assertEqual(len(events), 1)

        dialog._syncing = True
        dialog._on_control_changed()
        self.assertEqual(len(events), 1)

        dialog._syncing = False
        dialog._sliders[1].setValue(10)
        dialog._on_control_changed()
        self.assertGreaterEqual(len(events), 2)

        for slider in dialog._sliders:
            slider.setValue(80)
        dialog._reset_gains()
        self.assertTrue(all(slider.value() == 0 for slider in dialog._sliders))
        self.assertGreaterEqual(len(events), 3)

    def test_equalizer_dialog_close_is_hide_only(self):
        dialog = equalizer.EqualizerDialog()
        event = mock.Mock()
        dialog.hide = mock.Mock()

        dialog.closeEvent(event)

        event.ignore.assert_called_once()
        dialog.hide.assert_called_once()


if __name__ == "__main__":
    unittest.main()

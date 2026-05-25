import unittest
from unittest import mock

import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer

from isrc_manager.media import equalizer_player
from isrc_manager.media.equalizer_player import LiveEqualizerPlayer, _LiveBiquad
from tests.qt_test_helpers import require_qapplication


class LiveBiquadTests(unittest.TestCase):
    def test_live_biquad_defaults_are_inactive_until_gain_applied(self):
        biquad = _LiveBiquad()
        samples = np.array([[0.2, -0.2]], dtype=np.float32)
        out = biquad.process(samples)
        self.assertFalse(biquad.active)
        self.assertTrue(np.array_equal(out, samples))

        biquad.configure(
            filter_type="peaking",
            frequency_hz=440.0,
            q=1.0,
            gain_db=0.05,
            sample_rate=44100,
            channels=2,
        )
        self.assertTrue(biquad.active)

    def test_live_biquad_resets_when_gain_returns_to_neutral(self):
        biquad = _LiveBiquad()
        biquad.configure(
            filter_type="peaking",
            frequency_hz=440.0,
            q=1.0,
            gain_db=2.5,
            sample_rate=44100,
            channels=2,
        )

        biquad.configure(
            filter_type="peaking",
            frequency_hz=440.0,
            q=1.0,
            gain_db=0.0,
            sample_rate=44100,
            channels=2,
        )
        self.assertFalse(biquad.active)


class LiveEqualizerPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_set_decoded_source_normalizes_and_shapes_samples(self):
        player = LiveEqualizerPlayer()
        player._set_state = unittest.mock.Mock()
        player.setDecodedSource(np.array([1.0, -1.2, 0.3], dtype=np.float32), 22050)

        snapshot = player.decoded_source_snapshot()
        self.assertIsNotNone(snapshot)
        samples, sample_rate = snapshot
        self.assertEqual(sample_rate, 22050)
        self.assertEqual(samples.shape, (3, 1))
        self.assertTrue(np.all(samples >= -1.0))

    def test_set_decoded_source_bypasses_clipping_when_assume_prepared_true(self):
        player = LiveEqualizerPlayer()
        player.setDecodedSource(
            np.array([[2.0, -2.0], [0.5, -0.5]], dtype=np.float32),
            44100,
            assume_prepared=True,
        )

        samples, _ = player.decoded_source_snapshot()
        self.assertEqual(samples.shape, (2, 2))
        self.assertEqual(samples[0, 0], 2.0)

    def test_set_decoded_source_none_rejects_and_clears_state(self):
        player = LiveEqualizerPlayer()
        player.setDecodedSource(np.array([[0.1, 0.2]], dtype=np.float32), 44100)
        player.setDecodedSource(None, 44100)
        self.assertIsNone(player.decoded_source_snapshot())

    def test_buffer_byte_count_uses_channels(self):
        player = LiveEqualizerPlayer()
        player._channels = 2
        self.assertEqual(player.buffer_byte_count(), 4096)

    def test_set_state_only_emits_on_change(self):
        player = LiveEqualizerPlayer()
        states: list[QMediaPlayer.PlaybackState] = []
        player.playbackStateChanged.connect(lambda state: states.append(state))

        player._set_state(QMediaPlayer.PlaybackState.PlayingState)
        player._set_state(QMediaPlayer.PlaybackState.PlayingState)

        self.assertEqual(states, [QMediaPlayer.PlaybackState.PlayingState])

    def test_apply_pan_locked_handles_stereo_and_single_channel_paths(self):
        player = LiveEqualizerPlayer()
        player._equalizer_settings["pan"] = 0.5
        stereo = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float64)
        left = player._apply_pan_locked(stereo)
        self.assertAlmostEqual(float(left[0, 0]), 0.5)
        self.assertAlmostEqual(float(left[0, 1]), 1.0)

        mono = np.array([[1.0], [1.0]], dtype=np.float64)
        left_mono = player._apply_pan_locked(mono)
        self.assertTrue(np.array_equal(left_mono, mono))

    def test_remember_output_samples_tracks_recent_history_shape(self):
        player = LiveEqualizerPlayer()
        first = np.ones((5, 2), dtype=np.float64)
        player._remember_output_samples_locked(first)
        self.assertEqual(player._recent_output_samples.shape, (5, 2))

        second = np.full((3, 2), 2.0, dtype=np.float64)
        player._remember_output_samples_locked(second)
        self.assertTrue(np.allclose(player._recent_output_samples[-3:], second))

    def test_read_audio_bytes_returns_empty_and_marks_pending_without_source(self):
        player = LiveEqualizerPlayer()
        self.assertEqual(player._read_audio_bytes(4096), b"")
        self.assertTrue(player._pending_finish)

    def test_repair_task_applies_read_and_pan_with_mocked_equalizer(self):
        player = LiveEqualizerPlayer()
        player._equalizer_settings["enabled"] = True
        player._equalizer_settings["pan"] = 0.25
        player._channels = 2
        player._filters = []
        player._samples = np.array(
            [[0.4, 0.2], [0.1, 0.05], [0.0, -0.1], [0.2, -0.2]],
            dtype=np.float64,
        )
        player._position_frames = 0

        data = player._read_audio_bytes(1024)
        self.assertIsInstance(data, (bytes, bytearray))
        self.assertGreater(len(data), 0)

    def test_which_prefers_shutil_which_result(self):
        with mock.patch.object(equalizer_player.shutil, "which", return_value="/usr/bin/ffmpeg"):
            self.assertEqual(equalizer_player._which("ffmpeg"), "/usr/bin/ffmpeg")

    def test_which_falls_back_to_platform_search_paths(self):
        with (
            mock.patch.object(equalizer_player.shutil, "which", return_value=None),
            mock.patch.object(equalizer_player.platform, "system", return_value="linux"),
            mock.patch.object(
                equalizer_player.os.path, "exists", lambda path: path == "/usr/local/bin/ffmpeg"
            ),
        ):
            self.assertEqual(equalizer_player._which("ffmpeg"), "/usr/local/bin/ffmpeg")

    def test_decode_audio_file_prefers_ffmpeg_when_available(self):
        samples = np.array([0.1, -0.1, 0.2, -0.2], dtype="<f4")
        with (
            mock.patch.object(equalizer_player, "_which", return_value="/usr/bin/ffmpeg"),
            mock.patch.object(
                equalizer_player.subprocess, "check_output", return_value=samples.tobytes()
            ),
        ):
            values, sample_rate = equalizer_player._decode_audio_file("in.wav")

        self.assertEqual(sample_rate, 44100)
        self.assertEqual(values.shape, (2, 2))
        self.assertTrue(np.allclose(values[0], [0.1, -0.1], atol=1e-6))

    def test_decode_audio_file_falls_back_to_soundfile_for_mono_path(self):
        mono = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
        fake_soundfile = mock.Mock()
        fake_soundfile.read.return_value = (mono, 22050)

        with (
            mock.patch.object(equalizer_player, "_which", return_value=None),
            mock.patch.object(
                equalizer_player.subprocess, "check_output", side_effect=RuntimeError("blocked")
            ),
            mock.patch.dict("sys.modules", {"soundfile": fake_soundfile}),
        ):
            values, sample_rate = equalizer_player._decode_audio_file("in.wav")

        self.assertEqual(sample_rate, 22050)
        self.assertEqual(values.shape, (3, 2))
        self.assertTrue(np.allclose(values[:, 0], values[:, 1], atol=1e-6))

    def test_decode_audio_file_falls_back_to_soundfile_for_multichannel_path(self):
        stereo_plus = np.array(
            [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]],
            dtype=np.float32,
        )
        fake_soundfile = mock.Mock()
        fake_soundfile.read.return_value = (stereo_plus, 32000)

        with (
            mock.patch.object(equalizer_player, "_which", return_value=None),
            mock.patch.object(
                equalizer_player.subprocess, "check_output", side_effect=RuntimeError("blocked")
            ),
            mock.patch.dict("sys.modules", {"soundfile": fake_soundfile}),
        ):
            values, sample_rate = equalizer_player._decode_audio_file("in.wav")

        self.assertEqual(sample_rate, 32000)
        self.assertEqual(values.shape, (2, 2))
        self.assertTrue(np.allclose(values[:, 0], stereo_plus[:, 0], atol=1e-6))
        self.assertTrue(np.allclose(values[:, 1], stereo_plus[:, 1], atol=1e-6))

    def test_decode_audio_file_raises_runtime_error_when_decode_fails(self):
        with (
            mock.patch.object(equalizer_player, "_which", return_value=None),
            mock.patch.object(
                equalizer_player.subprocess, "check_output", side_effect=RuntimeError("blocked")
            ),
            mock.patch.object(equalizer_player, "sf", create=True, spec_set=(), new=None),
        ):
            with self.assertRaises(RuntimeError):
                equalizer_player._decode_audio_file("in.wav")

    def test_set_source_short_circuits_and_clears_on_empty_qurl(self):
        player = LiveEqualizerPlayer()
        player._duration_ms = 900
        player.setSource(QUrl())

        self.assertEqual(player.duration(), 0)
        self.assertEqual(player.position(), 0)

    def test_set_source_uses_decoder_when_url_provided(self):
        player = LiveEqualizerPlayer()
        samples = np.ones((22050, 2), dtype=np.float32)

        with mock.patch.object(
            equalizer_player, "_decode_audio_file", return_value=(samples, 22050)
        ):
            player.setSource(QUrl.fromLocalFile("/tmp/test.wav"))

        self.assertEqual(player.duration(), 1000)
        self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)
        assert player.decoded_source_snapshot() is not None

    def test_set_source_error_bubbles_up(self):
        player = LiveEqualizerPlayer()
        with mock.patch.object(
            equalizer_player, "_decode_audio_file", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                player.setSource(QUrl.fromLocalFile("/tmp/test.wav"))

    def test_start_sink_uses_fallback_constructor_on_type_error(self):
        calls: list[tuple[int, int]] = []

        class _FakeSinkIO:
            def write(self, data):
                calls.append((len(data), 0))
                return len(data)

        class _FakeSink:
            def __init__(self, *args):  # noqa: ANN002
                if len(args) == 3:
                    raise TypeError("type mismatch")
                self._io = _FakeSinkIO()

            def setBufferSize(self, *_args):  # noqa: ANN002
                return None

            def start(self):
                return self._io

            def stop(self):
                return None

            def deleteLater(self):
                return None

        player = LiveEqualizerPlayer()
        player._samples = np.zeros((16, 2), dtype=np.float32)
        player._position_frames = 0
        player._sample_rate = 44100
        with mock.patch.object(equalizer_player, "QAudioSink", _FakeSink):
            self.assertTrue(player._start_sink())
        self.assertIsNotNone(player._sink)
        self.assertIsNotNone(player._sink_io)

    def test_start_sink_returns_false_when_sink_creation_fails(self):
        class _FailingSink:  # noqa: PLW0612
            def __init__(self, *args):  # noqa: ANN002
                raise RuntimeError("cannot create")

        player = LiveEqualizerPlayer()
        with mock.patch.object(equalizer_player, "QAudioSink", _FailingSink):
            self.assertFalse(player._start_sink())

    def test_start_sink_returns_false_when_sink_io_is_none(self):
        class _NoIoSink:
            def __init__(self, *args, **kwargs):
                pass

            def setBufferSize(self, *_args):  # noqa: ANN002
                return None

            def start(self):
                return None

            def stop(self):
                return None

            def deleteLater(self):
                return None

        player = LiveEqualizerPlayer()
        player._samples = np.zeros((4, 2), dtype=np.float32)
        with mock.patch.object(equalizer_player, "QAudioSink", _NoIoSink):
            self.assertFalse(player._start_sink())

    def test_play_starts_when_sink_ready(self):
        player = LiveEqualizerPlayer()
        player._samples = np.zeros((4, 2), dtype=np.float32)
        with mock.patch.object(player, "_start_sink", return_value=True):
            player.play()
            self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)

    def test_play_does_not_start_without_source(self):
        player = LiveEqualizerPlayer()
        with mock.patch.object(player, "_start_sink") as mock_start_sink:
            player.play()
            self.assertFalse(mock_start_sink.called)

    def test_emit_position_tick_finishes_when_pending_and_playing(self):
        player = LiveEqualizerPlayer()
        player._state = QMediaPlayer.PlaybackState.PlayingState
        player._samples = np.ones((4, 2), dtype=np.float64)
        player._position_frames = 4
        player._pending_finish = True
        with mock.patch.object(player, "_finish_playback") as finish:
            player._emit_position_tick()
            finish.assert_called_once()

    def test_emit_spectrum_tick_uses_recent_samples_and_settings(self):
        player = LiveEqualizerPlayer()
        player._state = QMediaPlayer.PlaybackState.PlayingState
        player._samples = np.ones((128, 2), dtype=np.float64)
        player._position_frames = 128
        player._recent_output_samples = np.ones((64, 2), dtype=np.float64)

        with mock.patch.object(player, "_publish_spectrum_frame") as publish:
            player._emit_spectrum_tick()
            assert publish.call_args is not None
            args = publish.call_args.args
            self.assertEqual(args[2], None)

        player._recent_output_samples = None
        with mock.patch.object(player, "_publish_spectrum_frame") as publish:
            player._emit_spectrum_tick()
            args = publish.call_args.args
            self.assertIsNotNone(args[2])

    def test_publish_spectrum_frame_ignores_short_chunk(self):
        player = LiveEqualizerPlayer()
        emissions: list[float] = []
        player.spectrumFrameChanged.connect(emissions.append)

        player._publish_spectrum_frame(
            np.ones((2, 2)), 44100, {"enabled": True, "gains": [0.0] * 8, "pan": 0.0}
        )
        self.assertEqual(len(emissions), 0)

    def test_publish_spectrum_frame_emits_frame_when_enabled(self):
        player = LiveEqualizerPlayer()
        emissions: list[float] = []
        player.spectrumFrameChanged.connect(emissions.append)

        player.set_equalizer_settings({"enabled": True, "gains": [0.0] * 8, "pan": 0.2})
        player._spectrum_reference = 0.0
        settings = player._equalizer_settings
        with mock.patch.object(
            player, "_equalizer_response_for_frequencies", return_value=np.ones(96)
        ):
            player._publish_spectrum_frame(
                np.linspace(-1.0, 1.0, 100, dtype=np.float64).reshape(-1, 1).repeat(2, axis=1),
                44100,
                settings,
            )
        self.assertEqual(len(emissions), 1)
        self.assertIsInstance(emissions[0], list)


if __name__ == "__main__":
    unittest.main()

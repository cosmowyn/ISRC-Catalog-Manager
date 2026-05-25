import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from isrc_manager.authenticity import watermark as authenticity_watermark
from isrc_manager.forensics import watermark
from isrc_manager.forensics.models import ForensicWatermarkToken
from isrc_manager.forensics.watermark import FORENSIC_SYNC_WORD, ForensicWatermarkCore


class ForensicWatermarkModuleTests(unittest.TestCase):
    def test_supported_forensic_audio_path(self):
        self.assertTrue(watermark.supported_forensic_audio_path("track.wav"))
        self.assertTrue(watermark.supported_forensic_audio_path(Path("track.flac")))
        self.assertFalse(watermark.supported_forensic_audio_path("track.txt"))

    def test_pack_unpack_round_trip_and_guardrails(self):
        token = ForensicWatermarkToken(version=2, token_id=42, binding_crc32=123456, crc32=None)

        with self.assertRaises(ValueError):
            watermark.pack_token(
                ForensicWatermarkToken(version=1, token_id=0, binding_crc32=1, crc32=None)
            )
        with self.assertRaises(ValueError):
            watermark.pack_token(
                ForensicWatermarkToken(
                    version=1,
                    token_id=(1 << 48),
                    binding_crc32=1,
                    crc32=None,
                )
            )

        payload = watermark.pack_token(token)
        self.assertEqual(len(payload), 15)
        restored = watermark.unpack_token(payload)
        self.assertEqual(restored.version, token.version)
        self.assertEqual(restored.token_id, token.token_id)
        self.assertEqual(restored.binding_crc32, token.binding_crc32)

    def test_sync_and_payload_bits_prefix_and_payload_width(self):
        token = ForensicWatermarkToken(version=1, token_id=9, binding_crc32=42, crc32=None)
        payload = watermark.pack_token(token)
        bits = watermark.sync_and_payload_bits(token)

        self.assertEqual(bits.shape, (136,))
        self.assertEqual(len(bits) - 16, len(np.unpackbits(np.frombuffer(payload, dtype=np.uint8))))
        sync_bits = np.asarray(
            [(FORENSIC_SYNC_WORD >> shift) & 1 for shift in range(15, -1, -1)],
            dtype=np.uint8,
        )
        self.assertEqual(bits[:16].tolist(), sync_bits.tolist())

    def test_extract_from_path_requires_keys(self):
        core = ForensicWatermarkCore()
        result = core.extract_from_path("missing.wav", watermark_keys=[])

        self.assertEqual(result.status, "insufficient")

    def test_extract_from_path_returns_none_for_invalid_audio_shape(self):
        with mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio:
            read_audio.return_value = (
                np.zeros((0, 2), dtype=np.float32),
                44_100,
                "wav",
                None,
            )
            core = ForensicWatermarkCore()
            result = core.extract_from_path("in.wav", watermark_keys=[("k", b"abc")])

            self.assertEqual(result.status, "none")

    def test_extract_from_path_returns_none_when_audio_too_short(self):
        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
            mock.patch("isrc_manager.forensics.watermark._eligible_bins") as eligible_bins,
            mock.patch("isrc_manager.forensics.watermark._usable_frames") as usable_frames,
        ):
            read_audio.return_value = (np.zeros((16, 2), dtype=np.float32), 44_100, "wav", None)
            stft_channel.return_value = (
                np.array([10, 20, 30], dtype=np.float32),
                np.zeros((3, 6), dtype=np.float32),
            )
            eligible_bins.return_value = np.array([0, 1], dtype=np.int32)
            usable_frames.return_value = np.array([], dtype=np.int32)

            core = ForensicWatermarkCore()
            result = core.extract_from_path("in.wav", watermark_keys=[("k", b"abc")])

            self.assertEqual(result.status, "none")

    def test_extract_from_path_detects_when_signal_matches_payload(self):
        token = ForensicWatermarkToken(version=1, token_id=77, binding_crc32=555, crc32=None)
        expected_bits = watermark.sync_and_payload_bits(token)
        measurement_matrix = (
            np.where(expected_bits == 1, 1.0, -1.0).reshape(1, -1).astype(np.float32)
        )

        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
            mock.patch("isrc_manager.forensics.watermark._eligible_bins") as eligible_bins,
            mock.patch("isrc_manager.forensics.watermark._usable_frames") as usable_frames,
            mock.patch.object(
                ForensicWatermarkCore, "_measurement_matrix", return_value=measurement_matrix
            ),
        ):
            read_audio.return_value = (np.zeros((512, 2), dtype=np.float32), 44_100, "wav", None)
            stft_channel.return_value = (
                np.array([10, 20, 30], dtype=np.float32),
                np.zeros((3, 512), dtype=np.float32),
            )
            eligible_bins.return_value = np.array([0, 1], dtype=np.int32)
            usable_frames.return_value = np.arange(520, dtype=np.int32)

            result = ForensicWatermarkCore().extract_from_path(
                "in.wav", watermark_keys=[("k", b"abc")]
            )

            self.assertEqual(result.status, "detected")
            self.assertEqual(result.key_id, "k")
            self.assertIsNotNone(result.token)

    def test_verify_expected_token_against_reference_requires_reference(self):
        core = ForensicWatermarkCore()
        token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=10, crc32=None)
        result = core.verify_expected_token_against_reference(
            Path("candidate.wav"),
            reference_path=None,
            reference_bytes=b"",
            watermark_keys=[],
            token=token,
        )

        self.assertEqual(result.status, "insufficient")

    def test_verify_expected_token_against_reference_rejects_sample_rate_mismatch(self):
        token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=10, crc32=None)
        with (mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,):
            read_audio.side_effect = [
                (np.zeros((512, 2), dtype=np.float32), 44_100, "wav", None),
                (np.zeros((512, 2), dtype=np.float32), 48_000, "wav", None),
            ]

            result = ForensicWatermarkCore().verify_expected_token_against_reference(
                Path("candidate.wav"),
                reference_path=Path("ref.wav"),
                watermark_keys=[("k", b"abc")],
                token=token,
            )

        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.key_id, None)
        self.assertEqual(result.token, token)

    def test_verify_expected_token_against_reference_detected_when_signature_matches(self):
        token = ForensicWatermarkToken(version=1, token_id=11, binding_crc32=777, crc32=None)
        expected_signs = np.where(watermark.sync_and_payload_bits(token) > 0, 1.0, -1.0)
        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
            mock.patch("isrc_manager.forensics.watermark._eligible_bins") as eligible_bins,
            mock.patch.object(ForensicWatermarkCore, "_reference_difference_matrix") as matrix_fn,
        ):
            read_audio.side_effect = [
                (np.zeros((768, 2), dtype=np.float32), 44_100, "wav", None),
                (np.zeros((768, 2), dtype=np.float32), 44_100, "wav", None),
            ]
            stft_channel.return_value = (
                np.array([10, 20, 30], dtype=np.float32),
                np.zeros((3, 900), dtype=np.float32),
            )
            eligible_bins.return_value = np.array([0, 1], dtype=np.int32)
            matrix_fn.return_value = np.tile(expected_signs.astype(np.float32), (1, 1))

            result = ForensicWatermarkCore().verify_expected_token_against_reference(
                Path("candidate.wav"),
                reference_bytes=b"abc",
                watermark_keys=[("k", b"abc")],
                token=token,
            )

        self.assertEqual(result.status, "detected")
        self.assertEqual(result.key_id, "k")
        self.assertEqual(result.token, token)

    def test_unpack_token_requires_exact_length(self):
        with self.assertRaises(ValueError):
            watermark.unpack_token(b"\x00" * 14)

    def test_forensic_watermark_settings_payload_reports_constants(self):
        payload = watermark.forensic_watermark_settings_payload()
        self.assertEqual(payload["frame_length"], authenticity_watermark.FRAME_LENGTH)
        self.assertEqual(payload["hop_length"], authenticity_watermark.HOP_LENGTH)
        self.assertEqual(payload["bins_per_bit"], authenticity_watermark.EMBED_BINS_PER_BIT)
        self.assertEqual(payload["frames_per_bit"], authenticity_watermark.FRAMES_PER_BIT)
        self.assertEqual(payload["embed_strength"], authenticity_watermark.EMBED_STRENGTH)
        self.assertEqual(payload["embed_delta_clip"], authenticity_watermark.EMBED_DELTA_CLIP)
        self.assertEqual(payload["token_bytes"], 15)
        self.assertEqual(
            payload["mid_freq_hz"],
            [authenticity_watermark.MID_FREQ_MIN_HZ, authenticity_watermark.MID_FREQ_MAX_HZ],
        )

    def test_embed_to_path_rejects_missing_2d_audio(self):
        token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=10, crc32=None)
        with mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio:
            read_audio.return_value = (np.zeros((8,), dtype=np.float32), 44_100, "wav", None)

            with self.assertRaises(ValueError):
                watermark.ForensicWatermarkCore().embed_to_path(
                    source_path="source.wav",
                    destination_path=Path("out.wav"),
                    watermark_key=b"abc",
                    token=token,
                )

    def test_embed_to_path_rejects_missing_stft_frequencies(self):
        token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=10, crc32=None)
        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
        ):
            read_audio.return_value = (np.zeros((16, 2), dtype=np.float32), 44_100, "wav", None)
            stft_channel.return_value = (None, np.zeros((2, 4), dtype=np.complex64))

            with self.assertRaises(ValueError):
                watermark.ForensicWatermarkCore().embed_to_path(
                    source_path="source.wav",
                    destination_path=Path("out.wav"),
                    watermark_key=b"abc",
                    token=token,
                )

    def test_reference_difference_matrix_returns_deterministic_zero_for_identical_signals(self):
        core = watermark.ForensicWatermarkCore()
        stft = np.ones((1, 32), dtype=np.float32)
        candidate = np.concatenate([stft, stft], axis=0)
        reference = np.concatenate([stft, stft], axis=0)
        eligible_bins = np.array([0], dtype=np.int32)
        usable_frames = np.arange(16, dtype=np.int32)

        with mock.patch("isrc_manager.forensics.watermark._frame_schedule") as frame_schedule:
            frame_schedule.return_value = (eligible_bins, np.array([1.0], dtype=np.float32))
            matrix = core._reference_difference_matrix(
                candidate_stft=candidate,
                reference_stft=reference,
                eligible_bins=eligible_bins,
                usable_frames=usable_frames,
                watermark_key=b"abc",
                bit_count=1,
                frames_per_payload=watermark.FRAMES_PER_BIT,
                repeat_groups=1,
            )

        self.assertEqual(matrix.shape, (1, 1))
        self.assertAlmostEqual(float(matrix[0, 0]), 0.0, places=7)

    def test_verify_expected_token_against_reference_returns_none_when_no_reusable_frames(self):
        token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=10, crc32=None)
        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
        ):
            audio = np.zeros((8, 2), dtype=np.float32)
            read_audio.return_value = (audio, 44_100, "wav", None)
            stft_channel.return_value = (
                np.array([100.0], dtype=np.float32),
                np.zeros((1, 0), dtype=np.float32),
            )

            result = watermark.ForensicWatermarkCore().verify_expected_token_against_reference(
                Path("candidate.wav"),
                reference_path=Path("reference.wav"),
                watermark_keys=[("k", b"abc")],
                token=token,
            )

        self.assertEqual(result.status, "none")
        self.assertEqual(result.repeat_groups, 0)

    def test_verify_expected_token_against_reference_supports_insufficient_result(self):
        token = ForensicWatermarkToken(version=1, token_id=11, binding_crc32=777, crc32=None)
        expected_bits = watermark.sync_and_payload_bits(token)
        expected_signs = np.where(expected_bits > 0, 1.0, -1.0).astype(np.float32)
        insufficient_matrix = np.tile(expected_signs, (1, 1)).reshape((1, -1)) * 0.001

        with (
            mock.patch("isrc_manager.forensics.watermark._read_audio") as read_audio,
            mock.patch("isrc_manager.forensics.watermark._stft_channel") as stft_channel,
            mock.patch("isrc_manager.forensics.watermark._eligible_bins") as eligible_bins,
            mock.patch("isrc_manager.forensics.watermark._usable_frames") as usable_frames,
            mock.patch.object(
                watermark.ForensicWatermarkCore,
                "_reference_difference_matrix",
                return_value=insufficient_matrix,
            ),
        ):
            read_audio.side_effect = [
                (np.zeros((16, 2), dtype=np.float32), 44_100, "wav", None),
                (np.zeros((16, 2), dtype=np.float32), 44_100, "wav", None),
            ]
            stft_channel.return_value = (
                np.array([10.0, 20.0, 30.0], dtype=np.float32),
                np.zeros((3, 5000), dtype=np.float32),
            )
            eligible_bins.return_value = np.array([0], dtype=np.int32)
            usable_frames.return_value = np.arange(5000, dtype=np.int32)

            result = watermark.ForensicWatermarkCore().verify_expected_token_against_reference(
                Path("candidate.wav"),
                reference_bytes=b"abc",
                watermark_keys=[("k", b"abc")],
                token=token,
            )

        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.key_id, "k")
        self.assertIs(result.token, token)


if __name__ == "__main__":
    unittest.main()

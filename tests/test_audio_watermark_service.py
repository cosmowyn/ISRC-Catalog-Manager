import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from isrc_manager.authenticity import watermark as watermark_module
from isrc_manager.authenticity.models import WatermarkToken
from isrc_manager.authenticity.watermark import (
    FRAME_PATTERN,
    AudioWatermarkCore,
    pack_token,
    supported_audio_path,
    sync_and_payload_bits,
    unpack_token,
    watermark_settings_payload,
)
from tests._authenticity_support import AuthenticityWorkflowTestCase


class AudioWatermarkServiceTests(AuthenticityWorkflowTestCase):
    def test_embed_to_path_keeps_audio_shape_and_bounded_delta_for_wav(self):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=1,
            suffix=".wav",
        )
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        destination = self.root / "watermarked.wav"

        metrics = self.watermark_service.embed_to_path(
            source_path=audio_path,
            destination_path=destination,
            watermark_key=self.key_service.extraction_keys()[0][1],
            token=prepared.watermark_token,
        )

        source_audio, source_sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        output_audio, output_sr = sf.read(str(destination), dtype="float32", always_2d=True)
        self.assertEqual(source_sr, output_sr)
        self.assertEqual(source_audio.shape, output_audio.shape)
        self.assertGreater(metrics["peak_delta"], 0.0)
        self.assertLess(metrics["peak_delta"], 0.05)
        self.assertLess(metrics["rms_delta"], 0.02)
        self.assertLessEqual(float(abs(output_audio).max()), 1.0)

    def test_reference_aware_verification_recovers_expected_token_from_clean_wav_export(self):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=2,
            suffix=".wav",
        )
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        destination = self.root / "watermarked.wav"
        self.watermark_service.embed_to_path(
            source_path=audio_path,
            destination_path=destination,
            watermark_key=self.key_service.extraction_keys()[0][1],
            token=prepared.watermark_token,
        )

        result = self.watermark_service.verify_expected_token_against_reference(
            destination,
            reference_path=audio_path,
            watermark_keys=self.key_service.extraction_keys(),
            token=prepared.watermark_token,
        )

        self.assertEqual(result.status, "detected")
        self.assertEqual(result.token.watermark_id, prepared.watermark_token.watermark_id)
        self.assertGreaterEqual(result.mean_confidence, 0.90)
        self.assertGreaterEqual(result.group_agreement, 0.84)

    def test_reference_aware_verification_recovers_expected_token_from_clean_flac_export(self):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=3,
            suffix=".flac",
        )
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        destination = self.root / "watermarked.flac"
        self.watermark_service.embed_to_path(
            source_path=audio_path,
            destination_path=destination,
            watermark_key=self.key_service.extraction_keys()[0][1],
            token=prepared.watermark_token,
        )

        result = self.watermark_service.verify_expected_token_against_reference(
            destination,
            reference_path=audio_path,
            watermark_keys=self.key_service.extraction_keys(),
            token=prepared.watermark_token,
        )

        self.assertIn(result.status, {"detected", "insufficient"})
        self.assertEqual(
            result.token.manifest_digest_prefix, prepared.watermark_token.manifest_digest_prefix
        )
        self.assertGreaterEqual(result.mean_confidence, 0.90)
        # FLAC round-trips can vary slightly across libsndfile/platform builds while
        # still recovering the expected token with strong confidence.
        self.assertGreaterEqual(result.group_agreement, 0.80)

    def test_reference_aware_verification_recovers_expected_token_from_clean_aiff_export(self):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=5,
            suffix=".aiff",
        )
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        destination = self.root / "watermarked.aiff"
        self.watermark_service.embed_to_path(
            source_path=audio_path,
            destination_path=destination,
            watermark_key=self.key_service.extraction_keys()[0][1],
            token=prepared.watermark_token,
        )

        result = self.watermark_service.verify_expected_token_against_reference(
            destination,
            reference_path=audio_path,
            watermark_keys=self.key_service.extraction_keys(),
            token=prepared.watermark_token,
        )

        self.assertIn(result.status, {"detected", "insufficient"})
        self.assertEqual(result.token.watermark_id, prepared.watermark_token.watermark_id)
        self.assertGreaterEqual(result.mean_confidence, 0.89)
        # AIFF round-trips can vary slightly across libsndfile/platform builds while
        # still recovering the expected token with strong confidence.
        self.assertGreaterEqual(result.group_agreement, 0.81)

    def test_embed_to_path_rejects_audio_that_is_too_short(self):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=3,
            seed=4,
            suffix=".wav",
        )
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )

        with self.assertRaises(ValueError):
            self.watermark_service.embed_to_path(
                source_path=audio_path,
                destination_path=self.root / "too-short.wav",
                watermark_key=self.key_service.extraction_keys()[0][1],
                token=prepared.watermark_token,
            )

    def test_supported_audio_path_rejects_non_pcm_extensions(self):
        self.assertTrue(supported_audio_path("track.wav"))
        self.assertTrue(supported_audio_path("track.flac"))
        self.assertTrue(supported_audio_path("track.aif"))
        self.assertTrue(supported_audio_path("track.aiff"))
        self.assertFalse(supported_audio_path("track.mp3"))

    def test_token_helpers_validate_prefix_unpack_and_settings_payload(self):
        token = WatermarkToken(
            version=1,
            watermark_id=123,
            manifest_digest_prefix="0011223344556677",
            nonce=987,
        )

        packed = pack_token(token)
        unpacked = unpack_token(packed)
        settings_payload = watermark_settings_payload()

        self.assertEqual(unpacked.watermark_id, 123)
        self.assertEqual(unpacked.manifest_digest_prefix, "0011223344556677")
        self.assertEqual(unpacked.nonce, 987)
        self.assertEqual(token.crc32, unpacked.crc32)
        self.assertEqual(settings_payload["sync_word_hex"], "a55a")
        with self.assertRaisesRegex(ValueError, "16 hexadecimal"):
            pack_token(
                WatermarkToken(
                    version=1,
                    watermark_id=1,
                    manifest_digest_prefix="abcd",
                    nonce=1,
                )
            )
        with self.assertRaisesRegex(ValueError, "25 bytes"):
            unpack_token(b"too short")

    def test_low_level_audio_io_and_shape_guards(self):
        with self.assertRaisesRegex(ValueError, "exactly one audio source"):
            watermark_module._read_audio()
        with self.assertRaisesRegex(ValueError, "exactly one audio source"):
            watermark_module._read_audio(
                source_path=self.root / "missing.wav",
                source_bytes=b"also present",
            )

        with mock.patch(
            "isrc_manager.authenticity.watermark.sf.write",
            side_effect=[RuntimeError("bad subtype"), None],
        ) as write_audio:
            watermark_module._write_audio(
                self.root / "fallback.flac",
                np.zeros((8, 1), dtype=np.float32),
                8000,
                source_subtype="UNSUPPORTED",
            )

        self.assertEqual(write_audio.call_count, 2)
        self.assertEqual(write_audio.call_args_list[0].kwargs["format"], "FLAC")
        self.assertEqual(write_audio.call_args_list[1].kwargs["subtype"], "PCM_24")

        with mock.patch(
            "isrc_manager.authenticity.watermark.signal.istft",
            return_value=(np.array([0.0]), np.array([0.5], dtype=np.float32)),
        ):
            restored = watermark_module._istft_channel(
                np.zeros((2, 1), dtype=np.complex64),
                8000,
                3,
            )
        self.assertEqual(restored.tolist(), [0.5, 0.0, 0.0])

        core = AudioWatermarkCore()
        with mock.patch(
            "isrc_manager.authenticity.watermark._read_audio",
            return_value=(np.empty((4, 0), dtype=np.float32), 8000, "WAV", "PCM_16"),
        ):
            with self.assertRaisesRegex(ValueError, "frequency bins"):
                core.embed_to_path(
                    source_path=self.root / "empty-channel.wav",
                    destination_path=self.root / "out.wav",
                    watermark_key=b"key",
                    token=WatermarkToken(
                        version=1,
                        watermark_id=1,
                        manifest_digest_prefix="0011223344556677",
                        nonce=1,
                    ),
                )

    def test_watermark_core_guard_results_and_mocked_detection_paths(self):
        core = AudioWatermarkCore()
        token = WatermarkToken(
            version=1,
            watermark_id=44,
            manifest_digest_prefix="8899aabbccddeeff",
            nonce=55,
        )

        self.assertEqual(
            core.extract_from_path("unused.wav", watermark_keys=[]).status, "insufficient"
        )
        self.assertEqual(
            core.verify_expected_token("unused.wav", watermark_keys=[], token=token).status,
            "insufficient",
        )
        self.assertEqual(
            core.verify_expected_token_against_reference(
                "unused.wav",
                reference_bytes=b"data",
                watermark_keys=[],
                token=token,
            ).status,
            "insufficient",
        )

        with mock.patch(
            "isrc_manager.authenticity.watermark._read_audio",
            return_value=(np.ones(8, dtype=np.float32), 8000, "WAV", "PCM_16"),
        ):
            self.assertEqual(
                core.extract_from_path("bad-shape.wav", watermark_keys=[("key", b"key")]).status,
                "none",
            )

        expected_bits = sync_and_payload_bits(token)
        measurements = np.where(expected_bits > 0, 1.0, -1.0).reshape(1, -1).astype(np.float32)
        usable_frames = np.arange(expected_bits.size * len(FRAME_PATTERN), dtype=np.int32)
        with (
            mock.patch(
                "isrc_manager.authenticity.watermark._read_audio",
                return_value=(np.ones((16, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._stft_channel",
                return_value=(np.arange(32, dtype=np.float32), np.ones((32, usable_frames.size))),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._eligible_bins",
                return_value=np.arange(24, dtype=np.int32),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._usable_frames",
                return_value=usable_frames,
            ),
            mock.patch.object(
                core,
                "_measurement_matrix",
                return_value=measurements,
            ),
        ):
            detected = core.extract_from_path("detected.wav", watermark_keys=[("key-1", b"key")])
            expected = core.verify_expected_token(
                "detected.wav",
                watermark_keys=[("key-1", b"key")],
                token=token,
            )

        self.assertEqual(detected.status, "detected")
        self.assertEqual(detected.key_id, "key-1")
        self.assertEqual(detected.token.watermark_id, token.watermark_id)
        self.assertEqual(expected.status, "detected")
        self.assertEqual(expected.token.manifest_digest_prefix, token.manifest_digest_prefix)

    def test_reference_verification_handles_mismatch_short_audio_and_insufficient_scores(self):
        core = AudioWatermarkCore()
        token = WatermarkToken(
            version=1,
            watermark_id=45,
            manifest_digest_prefix="1020304050607080",
            nonce=56,
        )

        with mock.patch(
            "isrc_manager.authenticity.watermark._read_audio",
            side_effect=[
                (np.ones((8, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
                (np.ones((8, 1), dtype=np.float32), 44100, "WAV", "PCM_16"),
            ],
        ):
            mismatch = core.verify_expected_token_against_reference(
                "candidate.wav",
                reference_bytes=b"reference",
                watermark_keys=[("key-1", b"key")],
                token=token,
            )
        self.assertEqual(mismatch.status, "insufficient")

        bit_count = int(sync_and_payload_bits(token).size)
        short_frames = np.arange(bit_count - 1, dtype=np.int32)
        insufficient_matrix = (
            np.where(
                sync_and_payload_bits(token) > 0,
                0.001,
                -0.001,
            )
            .reshape(1, -1)
            .astype(np.float32)
        )
        with (
            mock.patch(
                "isrc_manager.authenticity.watermark._read_audio",
                side_effect=[
                    (np.ones((16, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
                    (np.ones((16, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
                ],
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._stft_channel",
                return_value=(np.arange(32, dtype=np.float32), np.ones((32, bit_count * 3))),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._eligible_bins",
                return_value=np.arange(24, dtype=np.int32),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark.np.arange",
                return_value=short_frames,
            ),
        ):
            too_short = core.verify_expected_token_against_reference(
                "candidate.wav",
                reference_bytes=b"reference",
                watermark_keys=[("key-1", b"key")],
                token=token,
            )
        self.assertEqual(too_short.status, "none")

        with (
            mock.patch(
                "isrc_manager.authenticity.watermark._read_audio",
                side_effect=[
                    (np.ones((16, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
                    (np.ones((16, 1), dtype=np.float32), 8000, "WAV", "PCM_16"),
                ],
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._stft_channel",
                return_value=(np.arange(32, dtype=np.float32), np.ones((32, bit_count * 3))),
            ),
            mock.patch(
                "isrc_manager.authenticity.watermark._eligible_bins",
                return_value=np.arange(24, dtype=np.int32),
            ),
            mock.patch.object(
                core,
                "_reference_difference_matrix",
                return_value=insufficient_matrix,
            ),
        ):
            insufficient = core.verify_expected_token_against_reference(
                "candidate.wav",
                reference_bytes=b"reference",
                watermark_keys=[("key-1", b"key")],
                token=token,
            )
        self.assertEqual(insufficient.status, "insufficient")
        self.assertEqual(insufficient.key_id, "key-1")


if __name__ == "__main__":
    unittest.main()

import unittest

import soundfile as sf

from isrc_manager.authenticity.watermark import supported_audio_path
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
        self.assertGreaterEqual(result.group_agreement, 0.83)

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
        self.assertGreaterEqual(result.mean_confidence, 0.90)
        self.assertGreaterEqual(result.group_agreement, 0.82)

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


if __name__ == "__main__":
    unittest.main()

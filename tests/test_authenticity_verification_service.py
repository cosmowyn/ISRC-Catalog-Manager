import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.authenticity.models import (
    VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH,
    VERIFICATION_STATUS_NO_WATERMARK,
    VERIFICATION_STATUS_SIGNATURE_INVALID,
    VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    VERIFICATION_STATUS_VERIFIED,
)
from isrc_manager.releases import ReleasePayload, ReleaseTrackPlacement
from tests._authenticity_support import AuthenticityWorkflowTestCase


class AudioAuthenticityVerificationServiceTests(AuthenticityWorkflowTestCase):
    def _export_fixture(self):
        track_id, audio_path = self.create_track_with_audio(duration_seconds=30, seed=1)
        result = self.audio_service.export_watermarked_audio(
            output_dir=self.root / "exports",
            track_ids=[track_id],
            profile_name="Test Profile",
        )
        exported_path = Path(result.written_audio_paths[0])
        sidecar_path = Path(result.written_sidecar_paths[0])
        return track_id, audio_path, exported_path, sidecar_path, result

    def test_verify_file_reports_verified_authentic_for_exported_copy(self):
        _track_id, _audio_path, exported_path, _sidecar_path, _result = self._export_fixture()

        report = self.audio_service.verify_file(exported_path)

        self.assertEqual(report.status, VERIFICATION_STATUS_VERIFIED)
        self.assertTrue(report.signature_valid)
        self.assertFalse(report.exact_hash_match)
        self.assertGreaterEqual(report.extraction_confidence or 0.0, 0.90)
        self.assertGreaterEqual(report.fingerprint_similarity or 0.0, 0.92)

    def test_verify_file_reports_signature_invalid_when_manifest_signature_is_tampered(self):
        _track_id, _audio_path, exported_path, _sidecar_path, result = self._export_fixture()
        manifest_id = result.manifest_ids[0]
        with self.conn:
            self.conn.execute(
                "UPDATE AuthenticityManifests SET signature_b64=? WHERE manifest_id=?",
                ("broken-signature", manifest_id),
            )

        report = self.audio_service.verify_file(exported_path)

        self.assertEqual(report.status, VERIFICATION_STATUS_SIGNATURE_INVALID)
        self.assertFalse(report.signature_valid)

    def test_verify_file_reports_no_watermark_for_clean_reference_with_valid_sidecar(self):
        _track_id, audio_path, _exported_path, sidecar_path, _result = self._export_fixture()
        clean_copy = self.root / "exports" / "clean-copy.wav"
        shutil.copy2(audio_path, clean_copy)
        shutil.copy2(sidecar_path, clean_copy.with_suffix(".wav.authenticity.json"))

        report = self.audio_service.verify_file(clean_copy)

        self.assertEqual(report.status, VERIFICATION_STATUS_NO_WATERMARK)
        self.assertIn("stored source audio", " ".join(report.details))

    def test_verify_file_reports_reference_mismatch_when_fingerprint_check_fails(self):
        _track_id, _audio_path, exported_path, _sidecar_path, _result = self._export_fixture()

        with mock.patch(
            "isrc_manager.authenticity.service.fingerprint_similarity",
            return_value=0.80,
        ):
            report = self.audio_service.verify_file(exported_path)

        self.assertEqual(report.status, VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH)
        self.assertTrue(report.signature_valid)
        self.assertEqual(report.fingerprint_similarity, 0.80)

    def test_verify_file_reports_unsupported_for_non_pcm_target(self):
        target = self.root / "unsupported.mp3"
        target.write_bytes(b"not-an-audio-master")

        report = self.audio_service.verify_file(target)

        self.assertEqual(report.status, VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT)

    def test_export_watermarked_audio_writes_catalog_metadata_tags_to_exported_copy(self):
        track_id, _audio_path = self.create_track_with_audio(
            title="Lost in a Sea of Emotions",
            artist_name="Cosmowyn",
            album_title="Tides of Memory",
            duration_seconds=30,
            seed=7,
            suffix=".wav",
            release_date="2026-03-20",
            upc="987654321098",
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Cosmowyn Records",
            comments="Watermarked authenticity export",
            lyrics="instrumental",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Tides of Memory",
                primary_artist="Cosmowyn",
                album_artist="Cosmowyn",
                release_date="2026-03-21",
                label="Northern Current",
                upc="4006381333931",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=2,
                        track_number=4,
                        sequence_number=1,
                    )
                ],
            )
        )

        result = self.audio_service.export_watermarked_audio(
            output_dir=self.root / "exports",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        exported_tags = self.audio_tag_service.read_tags(result.written_audio_paths[0])

        self.assertEqual(exported_tags.title, "Lost in a Sea of Emotions")
        self.assertEqual(exported_tags.artist, "Cosmowyn")
        self.assertEqual(exported_tags.album, "Tides of Memory")
        self.assertEqual(exported_tags.album_artist, "Cosmowyn")
        self.assertEqual(exported_tags.track_number, 4)
        self.assertEqual(exported_tags.disc_number, 2)
        self.assertEqual(exported_tags.genre, "Ambient")
        self.assertEqual(exported_tags.composer, "M. van de Kleut")
        self.assertEqual(exported_tags.publisher, "Northern Current")
        self.assertEqual(exported_tags.release_date, "2026-03-21")
        self.assertEqual(exported_tags.isrc, "NL-TST-26-00001")
        self.assertEqual(exported_tags.upc, "4006381333931")
        self.assertEqual(exported_tags.comments, "Watermarked authenticity export")
        self.assertEqual(exported_tags.lyrics, "instrumental")


if __name__ == "__main__":
    unittest.main()

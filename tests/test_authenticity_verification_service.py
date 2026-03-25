import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.assets import AssetVersionPayload
from isrc_manager.authenticity.models import (
    VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH,
    VERIFICATION_STATUS_NO_WATERMARK,
    VERIFICATION_STATUS_SIGNATURE_INVALID,
    VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_VERIFIED_BY_LINEAGE,
)
from isrc_manager.releases import ReleasePayload, ReleaseTrackPlacement
from tests._authenticity_support import AuthenticityWorkflowTestCase


class AudioAuthenticityVerificationServiceTests(AuthenticityWorkflowTestCase):
    def _export_fixture(self, *, suffix: str = ".wav", seed: int = 1):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=seed,
            suffix=suffix,
        )
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

    def test_verify_file_reports_verified_authentic_for_aiff_exported_copy(self):
        _track_id, _audio_path, exported_path, _sidecar_path, _result = self._export_fixture(
            suffix=".aiff",
            seed=8,
        )

        report = self.audio_service.verify_file(exported_path)

        self.assertEqual(report.status, VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(report.document_type, "direct_watermark")
        self.assertEqual(report.verification_basis, "reference_guided_direct")

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

    def test_export_provenance_audio_writes_signed_lineage_sidecar_for_lossy_copy(self):
        track_id, _master_audio, direct_result = self.export_direct_authenticity_fixture()
        direct_manifest_id = direct_result.manifest_ids[0]
        derivative_audio = self.write_audio_fixture(
            "lineage-derivative.mp3",
            duration_seconds=30,
            seed=12,
            suffix=".mp3",
        )
        self.track_service.set_media_path(
            track_id,
            "audio_file",
            derivative_audio,
            storage_mode="managed_file",
        )
        master_asset = self.write_audio_fixture(
            "lineage-master.wav",
            duration_seconds=30,
            seed=1,
            suffix=".wav",
        )
        self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(master_asset),
                approved_for_use=True,
                primary_flag=True,
            )
        )

        result = self.audio_service.export_provenance_audio(
            output_dir=self.root / "exports" / "lineage",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        exported_path = Path(result.written_audio_paths[0])
        sidecar_path = Path(result.written_sidecar_paths[0])
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual(result.exported, 1)
        self.assertEqual(exported_path.suffix.lower(), ".mp3")
        self.assertEqual(sidecar["document_type"], "provenance_lineage")
        self.assertEqual(
            sidecar["derivative_document"]["payload"]["parent_authenticity"]["parent_manifest_id"],
            direct_manifest_id,
        )

    def test_export_provenance_audio_writes_catalog_metadata_tags_to_exported_copy(self):
        track_id, _master_audio, _direct_result = self.export_direct_authenticity_fixture()
        derivative_audio = self.write_audio_fixture(
            "lineage-tagged.mp3",
            duration_seconds=30,
            seed=40,
            suffix=".mp3",
        )
        self.track_service.set_media_path(
            track_id,
            "audio_file",
            derivative_audio,
            storage_mode="database",
        )
        self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(
                    self.write_audio_fixture(
                        "lineage-tagged-master.wav",
                        duration_seconds=30,
                        seed=1,
                        suffix=".wav",
                    )
                ),
                approved_for_use=True,
                primary_flag=True,
            )
        )

        result = self.audio_service.export_provenance_audio(
            output_dir=self.root / "exports" / "lineage_tagged",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        exported_tags = self.audio_tag_service.read_tags(result.written_audio_paths[0])

        self.assertEqual(exported_tags.title, "Authenticity Track")
        self.assertEqual(exported_tags.artist, "Moonwake")
        self.assertEqual(exported_tags.album, "Authenticity Tests")
        self.assertEqual(exported_tags.isrc, "NL-TST-26-00001")

    def test_verify_file_reports_verified_by_lineage_for_lossy_provenance_export(self):
        track_id, _master_audio, _direct_result = self.export_direct_authenticity_fixture()
        derivative_audio = self.write_audio_fixture(
            "lineage-verify.mp3",
            duration_seconds=30,
            seed=13,
            suffix=".mp3",
        )
        self.track_service.set_media_path(
            track_id,
            "audio_file",
            derivative_audio,
            storage_mode="managed_file",
        )
        master_asset = self.write_audio_fixture(
            "lineage-verify-master.wav",
            duration_seconds=30,
            seed=1,
            suffix=".wav",
        )
        self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(master_asset),
                approved_for_use=True,
                primary_flag=True,
            )
        )

        result = self.audio_service.export_provenance_audio(
            output_dir=self.root / "exports" / "lineage_verify",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        report = self.audio_service.verify_file(result.written_audio_paths[0])

        self.assertEqual(report.status, VERIFICATION_STATUS_VERIFIED_BY_LINEAGE)
        self.assertEqual(report.verification_basis, "provenance_lineage")
        self.assertEqual(report.document_type, "provenance_lineage")
        self.assertTrue(report.signature_valid)

    def test_verify_file_reports_signature_invalid_for_tampered_provenance_sidecar(self):
        track_id, _master_audio, _direct_result = self.export_direct_authenticity_fixture()
        derivative_audio = self.write_audio_fixture(
            "lineage-tampered.mp3",
            duration_seconds=30,
            seed=14,
            suffix=".mp3",
        )
        self.track_service.set_media_path(
            track_id,
            "audio_file",
            derivative_audio,
            storage_mode="managed_file",
        )
        master_asset = self.write_audio_fixture(
            "lineage-tampered-master.wav",
            duration_seconds=30,
            seed=1,
            suffix=".wav",
        )
        self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(master_asset),
                approved_for_use=True,
                primary_flag=True,
            )
        )

        result = self.audio_service.export_provenance_audio(
            output_dir=self.root / "exports" / "lineage_tampered",
            track_ids=[track_id],
            profile_name="Test Profile",
        )
        sidecar_path = Path(result.written_sidecar_paths[0])
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["derivative_document"]["signature_b64"] = "broken-signature"
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

        report = self.audio_service.verify_file(result.written_audio_paths[0])

        self.assertEqual(report.status, VERIFICATION_STATUS_SIGNATURE_INVALID)
        self.assertEqual(report.verification_basis, "provenance_lineage")

    def test_export_provenance_audio_skips_tracks_without_parent_direct_manifest(self):
        track_id, _audio_path = self.create_track_with_audio(
            duration_seconds=30,
            seed=15,
            suffix=".mp3",
        )

        result = self.audio_service.export_provenance_audio(
            output_dir=self.root / "exports" / "lineage_missing_parent",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        self.assertEqual(result.exported, 0)
        self.assertEqual(result.skipped, 1)
        self.assertTrue(result.warnings)

    def test_export_watermarked_audio_writes_catalog_metadata_tags_to_exported_copy(self):
        track_id, _audio_path = self.create_track_with_audio(
            title="Lost in a Sea of Emotions",
            artist_name="Moonwake",
            album_title="Tides of Memory",
            duration_seconds=30,
            seed=7,
            suffix=".wav",
            release_date="2026-03-20",
            upc="987654321098",
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Moonwake Records",
            comments="Watermarked authenticity export",
            lyrics="instrumental",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Tides of Memory",
                primary_artist="Moonwake",
                album_artist="Moonwake",
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
        self.assertEqual(exported_tags.artist, "Moonwake")
        self.assertEqual(exported_tags.album, "Tides of Memory")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
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

    def test_export_watermarked_audio_blob_backed_source_writes_catalog_metadata_tags(self):
        track_id, _audio_path = self.create_track_with_audio(
            title="Blob Authentic Export",
            artist_name="Moonwake",
            album_title="Blob Authentic Album",
            duration_seconds=30,
            seed=41,
            suffix=".wav",
            comments="Blob-backed authenticity export",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Blob Authentic Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-24",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=6,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.track_service.convert_media_storage_mode(track_id, "audio_file", "database")

        result = self.audio_service.export_watermarked_audio(
            output_dir=self.root / "exports" / "blob_authentic",
            track_ids=[track_id],
            profile_name="Test Profile",
        )

        exported_tags = self.audio_tag_service.read_tags(result.written_audio_paths[0])

        self.assertEqual(exported_tags.title, "Blob Authentic Export")
        self.assertEqual(exported_tags.album, "Blob Authentic Album")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
        self.assertEqual(exported_tags.track_number, 6)
        self.assertEqual(exported_tags.comments, "Blob-backed authenticity export")


if __name__ == "__main__":
    unittest.main()

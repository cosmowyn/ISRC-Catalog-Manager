import hashlib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from isrc_manager.forensics import (
    AUTHENTICITY_BASIS_FORENSIC_TRACE,
    DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
    FORENSIC_STATUS_MATCH_FOUND,
    FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
    FORENSIC_STATUS_NOT_DETECTED,
    FORENSIC_STATUS_TOKEN_UNRESOLVED,
    FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    ForensicExportCoordinator,
    ForensicExportRequest,
)
from isrc_manager.media import AudioConversionService
from isrc_manager.releases import ReleasePayload, ReleaseTrackPlacement
from tests._authenticity_support import AuthenticityWorkflowTestCase


def _sha256_for_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _DisabledForensicConversionService:
    def is_supported_target(
        self,
        format_id: str,
        *,
        managed_only: bool = False,
        capability_group: str | None = None,
    ) -> bool:
        return False

    def transcode(self, **_kwargs):
        raise AssertionError("Disabled conversion service should not be asked to transcode.")


class ForensicWatermarkServiceTests(AuthenticityWorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.conversion_service = AudioConversionService()
        self.forensic_service = ForensicExportCoordinator(
            conn=self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            tag_service=self.audio_tag_service,
            key_service=self.key_service,
            conversion_service=self.conversion_service,
            watermark_service=self.forensic_watermark_service,
        )

    def _require_mp3_forensic_support(self):
        if not self.conversion_service.is_supported_target(
            "mp3", capability_group="managed_forensic"
        ):
            self.skipTest("ffmpeg with managed forensic MP3 support is required for this test.")

    def test_forensic_export_reports_real_progress_stages_before_terminal_completion(self):
        self._require_mp3_forensic_support()
        track_id, _source_path = self.create_track_with_audio(
            title="Forensic Progress Source",
            artist_name="Moonwake",
            album_title="Forensic Progress Album",
            duration_seconds=30,
            seed=44,
            suffix=".wav",
        )
        progress_updates: list[tuple[int, int, str]] = []

        result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_id],
                output_dir=str(self.root / "forensic_progress_exports"),
                output_format="mp3",
                recipient_label="QA",
                share_label="Progress",
                profile_name="Test Profile",
            ),
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(result.exported, 1)
        messages = [message for _value, _maximum, message in progress_updates]
        self.assertIn("Resolving source 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Converting 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Preparing metadata 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Applying forensic watermark 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Hashing final output 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Registering derivative 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Registering forensic export 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Finalizing filename 1 of 1: Forensic Progress Source", messages)
        self.assertIn("Finalizing forensic export delivery…", messages)
        self.assertEqual(
            [value for value, _maximum, _message in progress_updates],
            sorted(value for value, _maximum, _message in progress_updates),
        )
        self.assertLess(progress_updates[-1][0], progress_updates[-1][1])
        self.assertTrue(all("finished" not in message.lower() for message in messages))

    def test_single_forensic_export_writes_tags_hash_derivative_and_forensic_ledger(self):
        self._require_mp3_forensic_support()
        track_id, source_path = self.create_track_with_audio(
            title="Forensic Source",
            artist_name="Moonwake",
            album_title="Forensic Album",
            duration_seconds=30,
            seed=21,
            suffix=".wav",
            release_date="2026-03-23",
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Moonwake Records",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Forensic Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-24",
                label="Northern Current",
                upc="4006381333931",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=2,
                        sequence_number=1,
                    )
                ],
            )
        )
        source_bytes_before = source_path.read_bytes()
        pre_watermark_hashes: list[str] = []
        real_embed = self.forensic_service.watermark_service.embed_export_path

        def _wrapped_embed(**kwargs):
            pre_watermark_hashes.append(_sha256_for_file(kwargs["source_path"]))
            return real_embed(**kwargs)

        with mock.patch.object(
            self.forensic_service.watermark_service,
            "embed_export_path",
            side_effect=_wrapped_embed,
        ):
            result = self.forensic_service.export(
                ForensicExportRequest(
                    track_ids=[track_id],
                    output_dir=str(self.root / "forensic_exports"),
                    output_format="mp3",
                    recipient_label="DJ Pool",
                    share_label="March Promo",
                    profile_name="Test Profile",
                )
            )

        self.assertEqual(result.exported, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(source_path.read_bytes(), source_bytes_before)
        output_path = Path(result.written_paths[0])
        exported_tags = self.audio_tag_service.read_tags(output_path)
        derivative_row = self.conn.execute(
            """
            SELECT workflow_kind, derivative_kind, authenticity_basis, watermark_applied,
                   metadata_embedded, output_filename, output_sha256
            FROM TrackAudioDerivatives
            """
        ).fetchone()
        forensic_row = self.conn.execute(
            """
            SELECT batch_id, derivative_export_id, track_id, key_id, token_version,
                   forensic_watermark_version, token_id, binding_crc32, recipient_label,
                   share_label, output_format, output_filename, output_sha256,
                   output_size_bytes, source_lineage_ref
            FROM ForensicWatermarkExports
            """
        ).fetchone()

        self.assertEqual(exported_tags.title, "Forensic Source")
        self.assertEqual(exported_tags.album, "Forensic Album")
        self.assertEqual(exported_tags.track_number, 2)
        self.assertEqual(exported_tags.disc_number, 1)
        self.assertEqual(exported_tags.publisher, "Northern Current")
        self.assertEqual(output_path.name, "Forensic Source.mp3")
        self.assertEqual(output_path.parent.name, "Forensic Album")
        self.assertEqual(derivative_row[0], "forensic_watermark_export")
        self.assertEqual(derivative_row[1], DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY)
        self.assertEqual(derivative_row[2], AUTHENTICITY_BASIS_FORENSIC_TRACE)
        self.assertEqual(derivative_row[3], 1)
        self.assertEqual(derivative_row[4], 1)
        self.assertEqual(derivative_row[5], output_path.name)
        self.assertEqual(derivative_row[6], _sha256_for_file(output_path))
        self.assertNotEqual(derivative_row[6], pre_watermark_hashes[0])
        self.assertEqual(forensic_row[0], result.batch_public_id)
        self.assertEqual(forensic_row[2], track_id)
        self.assertTrue(forensic_row[3].startswith("ed25519-"))
        self.assertEqual(forensic_row[4], 1)
        self.assertEqual(forensic_row[5], 1)
        self.assertGreater(int(forensic_row[6]), 0)
        self.assertGreaterEqual(int(forensic_row[7]), 0)
        self.assertEqual(forensic_row[8], "DJ Pool")
        self.assertEqual(forensic_row[9], "March Promo")
        self.assertEqual(forensic_row[10], "mp3")
        self.assertEqual(forensic_row[11], output_path.name)
        self.assertEqual(forensic_row[12], _sha256_for_file(output_path))
        self.assertGreater(int(forensic_row[13]), 0)
        self.assertTrue(str(forensic_row[14]).startswith(f"track-audio/{track_id}/"))

    def test_bulk_forensic_export_creates_unique_ids_and_zip(self):
        self._require_mp3_forensic_support()
        track_a, _ = self.create_track_with_audio(
            title="Forensic A",
            duration_seconds=30,
            seed=22,
            suffix=".wav",
        )
        track_b, _ = self.create_track_with_audio(
            title="Forensic B",
            duration_seconds=30,
            seed=23,
            suffix=".wav",
        )
        self.track_service.convert_media_storage_mode(track_b, "audio_file", "database")

        result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_a, track_b],
                output_dir=str(self.root / "forensic_bulk"),
                output_format="mp3",
                recipient_label="Playlist Team",
                share_label="Batch Review",
                profile_name="Test Profile",
            )
        )

        self.assertEqual(result.exported, 2)
        self.assertTrue(result.zip_path)
        self.assertEqual(len(set(result.forensic_export_ids)), 2)
        self.assertEqual(len(set(result.derivative_ids)), 2)
        zip_path = Path(result.zip_path)
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path) as archive:
            members = sorted(archive.namelist())
        self.assertEqual(len(members), 2)
        self.assertEqual(
            members,
            [
                "Authenticity Tests/Forensic A.mp3",
                "Authenticity Tests/Forensic B.mp3",
            ],
        )
        self.assertEqual(zip_path.name, "Authenticity Tests.zip")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM ForensicWatermarkExports").fetchone()[0],
            2,
        )

    def test_blob_backed_forensic_export_writes_catalog_metadata_tags(self):
        self._require_mp3_forensic_support()
        track_id, _ = self.create_track_with_audio(
            title="Blob Forensic Source",
            artist_name="Moonwake",
            album_title="Blob Forensic Album",
            duration_seconds=30,
            seed=42,
            suffix=".wav",
            publisher="Northern Current",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Blob Forensic Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-24",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=7,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.track_service.convert_media_storage_mode(track_id, "audio_file", "database")

        result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_id],
                output_dir=str(self.root / "forensic_blob_exports"),
                output_format="mp3",
                recipient_label="Blob Reviewer",
                share_label="Blob Batch",
                profile_name="Test Profile",
            )
        )

        exported_tags = self.audio_tag_service.read_tags(result.written_paths[0])

        self.assertEqual(exported_tags.title, "Blob Forensic Source")
        self.assertEqual(exported_tags.album, "Blob Forensic Album")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
        self.assertEqual(exported_tags.track_number, 7)
        self.assertEqual(exported_tags.publisher, "Northern Current")

    def test_inspect_file_resolves_known_exported_copy(self):
        self._require_mp3_forensic_support()
        track_id, _ = self.create_track_with_audio(
            title="Inspectable",
            duration_seconds=30,
            seed=24,
            suffix=".wav",
        )
        export_result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_id],
                output_dir=str(self.root / "inspectable_exports"),
                output_format="mp3",
                recipient_label="Reviewer",
                share_label="Leak Trace",
                profile_name="Test Profile",
            )
        )

        with mock.patch.object(
            self.forensic_service.watermark_service,
            "extract_from_path",
            return_value=mock.Mock(token=None),
        ):
            report = self.forensic_service.inspect_file(export_result.written_paths[0])

        self.assertEqual(report.status, FORENSIC_STATUS_MATCH_FOUND)
        self.assertTrue(report.forensic_export_id)
        self.assertEqual(report.track_id, track_id)
        self.assertEqual(report.recipient_label, "Reviewer")
        self.assertTrue(report.exact_hash_match)
        self.assertEqual(report.resolution_basis, "exact_output_hash")
        verification_row = self.conn.execute(
            """
            SELECT last_verification_status, last_verification_confidence
            FROM ForensicWatermarkExports
            """
        ).fetchone()
        self.assertEqual(verification_row[0], FORENSIC_STATUS_MATCH_FOUND)
        self.assertEqual(float(verification_row[1]), 1.0)

    def test_inspect_file_reports_unresolved_token_when_token_exists_but_row_is_missing(self):
        self._require_mp3_forensic_support()
        track_id, _ = self.create_track_with_audio(
            title="Unresolved Token",
            duration_seconds=30,
            seed=25,
            suffix=".wav",
        )
        export_result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_id],
                output_dir=str(self.root / "unresolved_exports"),
                output_format="mp3",
                profile_name="Test Profile",
            )
        )
        row = self.conn.execute(
            "SELECT token_id, binding_crc32 FROM ForensicWatermarkExports"
        ).fetchone()
        assert row is not None
        token_id, binding_crc32 = row
        with self.conn:
            self.conn.execute("DELETE FROM ForensicWatermarkExports")

        extraction_result = mock.Mock(
            token=mock.Mock(token_id=token_id, binding_crc32=binding_crc32),
            mean_confidence=0.88,
        )
        with mock.patch.object(
            self.forensic_service.watermark_service,
            "extract_from_path",
            return_value=extraction_result,
        ):
            report = self.forensic_service.inspect_file(export_result.written_paths[0])

        self.assertEqual(report.status, FORENSIC_STATUS_TOKEN_UNRESOLVED)
        self.assertEqual(report.token_id, token_id)

    def test_inspect_file_reports_low_confidence_when_reference_guided_match_is_weak(self):
        self._require_mp3_forensic_support()
        track_id, _ = self.create_track_with_audio(
            title="Low Confidence",
            duration_seconds=30,
            seed=26,
            suffix=".wav",
        )
        export_result = self.forensic_service.export(
            ForensicExportRequest(
                track_ids=[track_id],
                output_dir=str(self.root / "low_confidence_exports"),
                output_format="mp3",
                profile_name="Test Profile",
            )
        )
        candidate_path = self.root / "low-confidence-candidate.mp3"
        candidate_path.write_bytes(Path(export_result.written_paths[0]).read_bytes())
        existing_tags = self.audio_tag_service.read_tags(candidate_path)
        existing_tags.comments = "modified candidate"
        self.audio_tag_service.write_tags(candidate_path, existing_tags)
        with (
            mock.patch.object(
                self.forensic_service.watermark_service,
                "extract_from_path",
                return_value=mock.Mock(token=None),
            ),
            mock.patch.object(
                self.forensic_service.watermark_service,
                "verify_expected_token_against_reference",
                return_value=mock.Mock(
                    status="insufficient",
                    mean_confidence=0.63,
                    group_agreement=0.59,
                    sync_score=0.54,
                ),
            ),
        ):
            report = self.forensic_service.inspect_file(candidate_path)

        self.assertEqual(report.status, FORENSIC_STATUS_MATCH_LOW_CONFIDENCE)
        self.assertEqual(report.track_id, track_id)
        self.assertEqual(report.resolution_basis, "reference_guided_forensic")
        self.assertGreater(float(report.confidence_score or 0.0), 0.0)

    def test_inspect_file_reports_not_detected_for_clean_audio_without_matching_export(self):
        self._require_mp3_forensic_support()
        _track_id, clean_audio = self.create_track_with_audio(
            title="Clean Audio",
            duration_seconds=30,
            seed=27,
            suffix=".wav",
        )
        clean_mp3 = self.root / "clean-audio.mp3"
        self.conversion_service.transcode(
            source_path=clean_audio,
            destination_path=clean_mp3,
            target_id="mp3",
        )

        report = self.forensic_service.inspect_file(clean_mp3)

        self.assertEqual(report.status, FORENSIC_STATUS_NOT_DETECTED)
        self.assertEqual(report.resolution_basis, "no_match")

    def test_inspect_file_reports_unsupported_for_non_audio_input(self):
        bogus = self.root / "unsupported.bin"
        bogus.write_bytes(b"not audio")

        report = self.forensic_service.inspect_file(bogus)

        self.assertEqual(report.status, FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT)
        self.assertEqual(report.resolution_basis, "decode_failure")

    def test_export_rejects_mp3_when_forensic_capability_is_unavailable(self):
        track_id, _ = self.create_track_with_audio(
            title="No MP3",
            duration_seconds=30,
            seed=28,
            suffix=".wav",
        )
        disabled_service = ForensicExportCoordinator(
            conn=self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            tag_service=self.audio_tag_service,
            key_service=self.key_service,
            conversion_service=_DisabledForensicConversionService(),
            watermark_service=self.forensic_watermark_service,
        )

        with self.assertRaisesRegex(ValueError, "Unsupported forensic watermark target: mp3"):
            disabled_service.export(
                ForensicExportRequest(
                    track_ids=[track_id],
                    output_dir=str(self.root / "disabled_forensic"),
                    output_format="mp3",
                    profile_name="Test Profile",
                )
            )


if __name__ == "__main__":
    unittest.main()

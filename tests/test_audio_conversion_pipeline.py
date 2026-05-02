import hashlib
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import soundfile as sf

from isrc_manager.media.audio_formats import managed_lossy_target_profiles
from isrc_manager.media.conversion import AudioConversionResult, AudioConversionService
from isrc_manager.media.derivatives import (
    AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY,
    AUTHENTICITY_BASIS_DIRECT_WATERMARK,
    MANAGED_DERIVATIVE_KIND_LOSSY,
    MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
    MANAGED_DERIVATIVE_WORKFLOW_KIND,
    ExternalAudioConversionCoordinator,
    ExternalAudioConversionRequest,
    ManagedDerivativeExportCoordinator,
    ManagedDerivativeExportRequest,
)
from isrc_manager.releases import ReleasePayload, ReleaseTrackPlacement
from tests._authenticity_support import AuthenticityWorkflowTestCase


def _sha256_for_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _StubConversionService:
    def __init__(self):
        self._managed_authentic = {"wav", "flac", "aiff"}
        self._managed_lossy = {"mp3"}
        self._external = {"wav", "flac", "aiff", "mp3", "ogg", "opus"}
        self.calls: list[dict[str, object]] = []

    def is_supported_target(
        self,
        format_id: str,
        *,
        managed_only: bool = False,
        capability_group: str | None = None,
    ) -> bool:
        clean_id = str(format_id or "").strip().lower()
        if capability_group == "managed_authenticity":
            supported = self._managed_authentic
        elif capability_group == "managed_lossy":
            supported = self._managed_lossy
        elif capability_group in {"managed", "managed_any"}:
            supported = self._managed_authentic | self._managed_lossy
        elif managed_only:
            supported = self._managed_authentic
        else:
            supported = self._external
        return clean_id in supported

    def transcode(
        self,
        *,
        source_path: str | Path,
        destination_path: str | Path,
        target_id: str,
        metadata_behavior: str = "inherit",
    ) -> AudioConversionResult:
        self.calls.append(
            {
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "target_id": str(target_id),
                "metadata_behavior": str(metadata_behavior),
            }
        )
        data, sample_rate = sf.read(str(source_path), dtype="float32", always_2d=True)
        target = str(target_id or "").strip().lower()
        destination = Path(destination_path)
        if target == "flac":
            sf.write(destination, data, sample_rate, format="FLAC", subtype="PCM_24")
        elif target == "aiff":
            sf.write(destination, data, sample_rate, format="AIFF", subtype="PCM_24")
        elif target == "mp3":
            sf.write(destination, data, sample_rate, format="MP3", subtype="MPEG_LAYER_III")
        elif target == "ogg":
            sf.write(destination, data, sample_rate, format="OGG", subtype="VORBIS")
        elif target == "opus":
            sf.write(destination, data, sample_rate, format="OGG", subtype="OPUS")
        else:
            sf.write(destination, data, sample_rate, format="WAV", subtype="PCM_24")
        return AudioConversionResult(
            destination_path=destination, output_format=target, codec_name=None
        )


class AudioConversionPipelineTests(AuthenticityWorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.stub_conversion_service = _StubConversionService()

    def _managed_coordinator(self) -> ManagedDerivativeExportCoordinator:
        return ManagedDerivativeExportCoordinator(
            conn=self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            tag_service=self.audio_tag_service,
            authenticity_service=self.audio_service,
            conversion_service=self.stub_conversion_service,
        )

    def test_managed_export_from_managed_file_writes_tags_hash_and_ledger(self):
        track_id, source_path = self.create_track_with_audio(
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
            comments="Managed derivative export",
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
        source_bytes_before = source_path.read_bytes()
        pre_watermark_hashes: list[str] = []
        real_watermark = self.audio_service.watermark_catalog_derivative

        def _wrapped_watermark(**kwargs):
            pre_watermark_hashes.append(_sha256_for_file(kwargs["source_path"]))
            return real_watermark(**kwargs)

        with mock.patch.object(
            self.audio_service,
            "watermark_catalog_derivative",
            side_effect=_wrapped_watermark,
        ):
            result = self._managed_coordinator().export(
                ManagedDerivativeExportRequest(
                    track_ids=[track_id],
                    output_dir=self.root / "managed_exports",
                    output_format="flac",
                    derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
                    profile_name="Test Profile",
                )
            )

        self.assertEqual(result.exported, 1)
        self.assertEqual(result.skipped, 0)
        output_path = Path(result.written_paths[0])
        exported_tags = self.audio_tag_service.read_tags(output_path)
        derivative_row = self.conn.execute(
            """
            SELECT batch_id, track_id, workflow_kind, derivative_kind, authenticity_basis,
                   source_lineage_ref, watermark_applied, metadata_embedded, output_filename,
                   filename_hash_suffix, output_sha256, output_size_bytes, derivative_manifest_id
            FROM TrackAudioDerivatives
            """
        ).fetchone()
        batch_row = self.conn.execute(
            """
            SELECT batch_id, workflow_kind, derivative_kind, authenticity_basis, output_format,
                   zip_filename, requested_count, exported_count, skipped_count, package_mode, status
            FROM DerivativeExportBatches
            """
        ).fetchone()
        derivative_columns = [
            row[1]
            for row in self.conn.execute("PRAGMA table_info(TrackAudioDerivatives)").fetchall()
        ]

        self.assertEqual(source_path.read_bytes(), source_bytes_before)
        self.assertEqual(exported_tags.title, "Lost in a Sea of Emotions")
        self.assertEqual(exported_tags.album, "Tides of Memory")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
        self.assertEqual(exported_tags.track_number, 4)
        self.assertEqual(exported_tags.disc_number, 2)
        self.assertEqual(exported_tags.publisher, "Northern Current")
        self.assertEqual(exported_tags.upc, "4006381333931")
        self.assertEqual(output_path.name, "Lost in a Sea of Emotions.flac")
        self.assertEqual(output_path.parent.name, "Tides of Memory")
        self.assertIsNotNone(derivative_row)
        self.assertEqual(derivative_row[1], track_id)
        self.assertEqual(derivative_row[2], MANAGED_DERIVATIVE_WORKFLOW_KIND)
        self.assertEqual(derivative_row[3], MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC)
        self.assertEqual(derivative_row[4], AUTHENTICITY_BASIS_DIRECT_WATERMARK)
        self.assertTrue(str(derivative_row[5]).startswith(f"track-audio/{track_id}/"))
        self.assertEqual(derivative_row[6], 1)
        self.assertEqual(derivative_row[7], 1)
        self.assertEqual(derivative_row[8], output_path.name)
        self.assertEqual(derivative_row[9], "")
        self.assertEqual(derivative_row[10], _sha256_for_file(output_path))
        self.assertNotEqual(derivative_row[10], pre_watermark_hashes[0])
        self.assertGreater(int(derivative_row[11]), 0)
        self.assertTrue(derivative_row[12])
        self.assertEqual(batch_row[0], result.batch_public_id)
        self.assertEqual(batch_row[1], MANAGED_DERIVATIVE_WORKFLOW_KIND)
        self.assertEqual(batch_row[2], MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC)
        self.assertEqual(batch_row[3], AUTHENTICITY_BASIS_DIRECT_WATERMARK)
        self.assertEqual(batch_row[4], "flac")
        self.assertIsNone(batch_row[5])
        self.assertEqual(batch_row[6], 1)
        self.assertEqual(batch_row[7], 1)
        self.assertEqual(batch_row[8], 0)
        self.assertEqual(batch_row[9], "directory")
        self.assertEqual(batch_row[10], "completed")
        self.assertFalse(any("blob" in column.casefold() for column in derivative_columns))

    def test_managed_export_supports_blob_backed_source_without_mutating_source_bytes(self):
        track_id, _source_path = self.create_track_with_audio(
            title="Blob Master",
            artist_name="Moonwake",
            album_title="Blob Album",
            duration_seconds=30,
            seed=9,
            suffix=".wav",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Blob Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-24",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.track_service.convert_media_storage_mode(track_id, "audio_file", "database")
        before_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")

        result = self._managed_coordinator().export(
            ManagedDerivativeExportRequest(
                track_ids=[track_id],
                output_dir=self.root / "blob_managed_exports",
                output_format="aiff",
                derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
                profile_name="Test Profile",
            )
        )

        after_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")
        output_path = Path(result.written_paths[0])
        exported_tags = self.audio_tag_service.read_tags(output_path)

        self.assertEqual(result.exported, 1)
        self.assertEqual(before_bytes, after_bytes)
        self.assertEqual(output_path.suffix.lower(), ".aiff")
        self.assertEqual(exported_tags.title, "Blob Master")
        self.assertEqual(exported_tags.album, "Blob Album")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
        self.assertEqual(exported_tags.track_number, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
            1,
        )

    def test_managed_lossy_export_from_managed_file_writes_tags_hash_and_directory_batch(self):
        track_id, source_path = self.create_track_with_audio(
            title="Lossy Export Source",
            artist_name="Moonwake",
            album_title="Lossy Export Album",
            duration_seconds=30,
            seed=16,
            suffix=".wav",
            release_date="2026-03-22",
            upc="9780201379624",
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Northern Current",
            comments="Lossy managed export",
            lyrics="instrumental",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Lossy Export Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-23",
                label="Northern Current",
                upc="9780201379624",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=3,
                        sequence_number=1,
                    )
                ],
            )
        )
        source_bytes_before = source_path.read_bytes()
        post_tag_hashes: list[str] = []
        real_write_tags = self.audio_tag_service.write_tags

        def _wrapped_write_tags(path, tag_data):
            real_write_tags(path, tag_data)
            post_tag_hashes.append(_sha256_for_file(path))

        with (
            mock.patch.object(
                self.audio_service,
                "watermark_catalog_derivative",
            ) as watermark_mock,
            mock.patch.object(
                self.audio_tag_service,
                "write_tags",
                side_effect=_wrapped_write_tags,
            ),
        ):
            result = self._managed_coordinator().export(
                ManagedDerivativeExportRequest(
                    track_ids=[track_id],
                    output_dir=self.root / "managed_lossy_exports",
                    output_format="mp3",
                    derivative_kind=MANAGED_DERIVATIVE_KIND_LOSSY,
                    profile_name="Test Profile",
                )
            )

        self.assertEqual(result.exported, 1)
        self.assertEqual(result.skipped, 0)
        self.assertIsNone(result.zip_path)
        output_path = Path(result.written_paths[0])
        exported_tags = self.audio_tag_service.read_tags(output_path)
        derivative_row = self.conn.execute(
            """
            SELECT track_id, workflow_kind, derivative_kind, authenticity_basis, source_storage_mode,
                   output_format, output_suffix, output_filename, filename_hash_suffix, output_sha256,
                   derivative_manifest_id, metadata_embedded, output_size_bytes, watermark_applied
            FROM TrackAudioDerivatives
            """
        ).fetchone()
        batch_row = self.conn.execute(
            """
            SELECT batch_id, workflow_kind, derivative_kind, authenticity_basis, output_format,
                   zip_filename, requested_count, exported_count, skipped_count, package_mode, status
            FROM DerivativeExportBatches
            """
        ).fetchone()

        self.assertEqual(source_path.read_bytes(), source_bytes_before)
        watermark_mock.assert_not_called()
        self.assertEqual(output_path.suffix.lower(), ".mp3")
        self.assertEqual(output_path.name, "Lossy Export Source.mp3")
        self.assertEqual(output_path.parent.name, "Lossy Export Album")
        self.assertEqual(exported_tags.title, "Lossy Export Source")
        self.assertEqual(exported_tags.album, "Lossy Export Album")
        self.assertEqual(exported_tags.album_artist, "Moonwake")
        self.assertEqual(exported_tags.track_number, 3)
        self.assertEqual(exported_tags.disc_number, 1)
        self.assertEqual(exported_tags.publisher, "Northern Current")
        self.assertEqual(exported_tags.upc, "9780201379624")
        self.assertEqual(derivative_row[0], track_id)
        self.assertEqual(derivative_row[1], MANAGED_DERIVATIVE_WORKFLOW_KIND)
        self.assertEqual(derivative_row[2], MANAGED_DERIVATIVE_KIND_LOSSY)
        self.assertEqual(derivative_row[3], AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY)
        self.assertEqual(derivative_row[4], "managed_file")
        self.assertEqual(derivative_row[5], "mp3")
        self.assertEqual(derivative_row[6], ".mp3")
        self.assertEqual(derivative_row[7], output_path.name)
        self.assertEqual(derivative_row[8], "")
        self.assertEqual(derivative_row[9], _sha256_for_file(output_path))
        self.assertEqual(derivative_row[9], post_tag_hashes[0])
        self.assertIsNone(derivative_row[10])
        self.assertEqual(derivative_row[11], 1)
        self.assertGreater(int(derivative_row[12]), 0)
        self.assertEqual(derivative_row[13], 0)
        self.assertEqual(batch_row[0], result.batch_public_id)
        self.assertEqual(batch_row[1], MANAGED_DERIVATIVE_WORKFLOW_KIND)
        self.assertEqual(batch_row[2], MANAGED_DERIVATIVE_KIND_LOSSY)
        self.assertEqual(batch_row[3], AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY)
        self.assertEqual(batch_row[4], "mp3")
        self.assertIsNone(batch_row[5])
        self.assertEqual(batch_row[6], 1)
        self.assertEqual(batch_row[7], 1)
        self.assertEqual(batch_row[8], 0)
        self.assertEqual(batch_row[9], "directory")
        self.assertEqual(batch_row[10], "completed")

    def test_bulk_managed_lossy_export_zips_mixed_source_storage_modes(self):
        track_one, source_one = self.create_track_with_audio(
            title="Managed Lossy Source",
            duration_seconds=30,
            seed=17,
            suffix=".wav",
        )
        track_two, _source_two = self.create_track_with_audio(
            title="Blob Lossy Source",
            duration_seconds=30,
            seed=18,
            suffix=".wav",
        )
        self.track_service.convert_media_storage_mode(track_two, "audio_file", "database")
        source_one_bytes_before = source_one.read_bytes()
        source_two_bytes_before, _mime_type = self.track_service.fetch_media_bytes(
            track_two, "audio_file"
        )
        with mock.patch.object(
            self.audio_service,
            "watermark_catalog_derivative",
        ) as watermark_mock:
            result = self._managed_coordinator().export(
                ManagedDerivativeExportRequest(
                    track_ids=[track_one, track_two],
                    output_dir=self.root / "bulk_managed_lossy_exports",
                    output_format="mp3",
                    derivative_kind=MANAGED_DERIVATIVE_KIND_LOSSY,
                    profile_name="Test Profile",
                )
            )

        self.assertEqual(result.exported, 2)
        self.assertIsNotNone(result.zip_path)
        watermark_mock.assert_not_called()
        self.assertEqual(source_one.read_bytes(), source_one_bytes_before)
        after_blob_bytes, _mime_type = self.track_service.fetch_media_bytes(track_two, "audio_file")
        self.assertEqual(after_blob_bytes, source_two_bytes_before)
        archive_hashes: dict[str, str] = {}
        extracted_titles: set[str] = set()
        with zipfile.ZipFile(result.zip_path) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            self.assertEqual(
                set(names),
                {
                    "Authenticity Tests/Blob Lossy Source.mp3",
                    "Authenticity Tests/Managed Lossy Source.mp3",
                },
            )
            for name in names:
                archive_hashes[name] = hashlib.sha256(archive.read(name)).hexdigest()
            extract_root = Path(tempfile.mkdtemp(prefix="lossy-bulk-extract-"))
            self.addCleanup(shutil.rmtree, extract_root, True)
            for name in names:
                archive.extract(name, path=extract_root)
                extracted = extract_root / name
                extracted_titles.add(str(self.audio_tag_service.read_tags(extracted).title or ""))
        derivative_rows = self.conn.execute(
            """
            SELECT track_id, workflow_kind, derivative_kind, authenticity_basis, source_storage_mode,
                   output_format, output_filename, output_sha256, watermark_applied, derivative_manifest_id
            FROM TrackAudioDerivatives
            ORDER BY track_id
            """
        ).fetchall()
        batch_row = self.conn.execute(
            """
            SELECT batch_id, workflow_kind, derivative_kind, authenticity_basis, output_format,
                   zip_filename, exported_count, skipped_count, package_mode
            FROM DerivativeExportBatches
            """
        ).fetchone()

        self.assertEqual(extracted_titles, {"Managed Lossy Source", "Blob Lossy Source"})
        self.assertEqual(
            [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in derivative_rows],
            [
                (
                    track_one,
                    MANAGED_DERIVATIVE_WORKFLOW_KIND,
                    MANAGED_DERIVATIVE_KIND_LOSSY,
                    AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY,
                    "managed_file",
                    "mp3",
                ),
                (
                    track_two,
                    MANAGED_DERIVATIVE_WORKFLOW_KIND,
                    MANAGED_DERIVATIVE_KIND_LOSSY,
                    AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY,
                    "database",
                    "mp3",
                ),
            ],
        )
        self.assertTrue(all(row[6].endswith(".mp3") for row in derivative_rows))
        self.assertEqual(
            {row[6] for row in derivative_rows},
            {"Blob Lossy Source.mp3", "Managed Lossy Source.mp3"},
        )
        self.assertEqual({f"Authenticity Tests/{row[6]}" for row in derivative_rows}, set(names))
        self.assertTrue(
            all(archive_hashes[f"Authenticity Tests/{row[6]}"] == row[7] for row in derivative_rows)
        )
        self.assertTrue(all(row[8] == 0 for row in derivative_rows))
        self.assertTrue(all(row[9] is None for row in derivative_rows))
        self.assertEqual(batch_row[0], result.batch_public_id)
        self.assertEqual(batch_row[1], MANAGED_DERIVATIVE_WORKFLOW_KIND)
        self.assertEqual(batch_row[2], MANAGED_DERIVATIVE_KIND_LOSSY)
        self.assertEqual(batch_row[3], AUTHENTICITY_BASIS_CATALOG_LINEAGE_ONLY)
        self.assertEqual(batch_row[4], "mp3")
        self.assertEqual(batch_row[5], Path(result.zip_path).name)
        self.assertEqual(batch_row[6], 2)
        self.assertEqual(batch_row[7], 0)
        self.assertEqual(batch_row[8], "zip")

    def test_managed_lossy_export_supports_single_blob_backed_source_without_mutating_source_bytes(
        self,
    ):
        track_id, _source_path = self.create_track_with_audio(
            title="Blob Lossy Export",
            artist_name="Moonwake",
            album_title="Blob Lossy Album",
            duration_seconds=30,
            seed=19,
            suffix=".wav",
        )
        self.release_service.create_release(
            ReleasePayload(
                title="Blob Lossy Album",
                primary_artist="Moonwake",
                album_artist="Moonwake",
                release_date="2026-03-24",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=5,
                        sequence_number=1,
                    )
                ],
            )
        )
        self.track_service.convert_media_storage_mode(track_id, "audio_file", "database")
        before_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")

        with mock.patch.object(
            self.audio_service,
            "watermark_catalog_derivative",
        ) as watermark_mock:
            result = self._managed_coordinator().export(
                ManagedDerivativeExportRequest(
                    track_ids=[track_id],
                    output_dir=self.root / "blob_managed_lossy_exports",
                    output_format="mp3",
                    derivative_kind=MANAGED_DERIVATIVE_KIND_LOSSY,
                    profile_name="Test Profile",
                )
            )

        after_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")
        exported_tags = self.audio_tag_service.read_tags(result.written_paths[0])
        derivative_row = self.conn.execute(
            """
            SELECT source_storage_mode, output_format, watermark_applied
            FROM TrackAudioDerivatives
            """
        ).fetchone()

        self.assertEqual(result.exported, 1)
        watermark_mock.assert_not_called()
        self.assertEqual(before_bytes, after_bytes)
        self.assertEqual(Path(result.written_paths[0]).suffix.lower(), ".mp3")
        self.assertEqual(exported_tags.title, "Blob Lossy Export")
        self.assertEqual(exported_tags.album, "Blob Lossy Album")
        self.assertEqual(exported_tags.track_number, 5)
        self.assertEqual(derivative_row, ("database", "mp3", 0))

    def test_managed_lossless_export_still_requires_authenticity_support(self):
        track_id, _source_path = self.create_track_with_audio(
            title="Lossless Auth Required",
            duration_seconds=30,
            seed=22,
            suffix=".wav",
        )
        coordinator = ManagedDerivativeExportCoordinator(
            conn=self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            tag_service=self.audio_tag_service,
            authenticity_service=None,
            conversion_service=self.stub_conversion_service,
        )

        with self.assertRaisesRegex(RuntimeError, "requires audio authenticity support"):
            coordinator.export(
                ManagedDerivativeExportRequest(
                    track_ids=[track_id],
                    output_dir=self.root / "managed_lossless_without_auth",
                    output_format="flac",
                    derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
                    profile_name="Test Profile",
                )
            )

    def test_bulk_managed_export_zips_mixed_sources(self):
        track_one, _source_one = self.create_track_with_audio(
            title="Managed Source",
            duration_seconds=30,
            seed=4,
            suffix=".wav",
        )
        track_two, _source_two = self.create_track_with_audio(
            title="Blob Source",
            duration_seconds=30,
            seed=5,
            suffix=".wav",
        )
        self.track_service.convert_media_storage_mode(track_two, "audio_file", "database")

        result = self._managed_coordinator().export(
            ManagedDerivativeExportRequest(
                track_ids=[track_one, track_two],
                output_dir=self.root / "bulk_managed_exports",
                output_format="wav",
                derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
                profile_name="Test Profile",
            )
        )

        self.assertEqual(result.exported, 2)
        self.assertIsNotNone(result.zip_path)
        with zipfile.ZipFile(result.zip_path) as archive:
            names = archive.namelist()
        self.assertEqual(len(names), 2)
        self.assertEqual(
            set(names),
            {
                "Authenticity Tests/Blob Source.wav",
                "Authenticity Tests/Managed Source.wav",
            },
        )
        batch_row = self.conn.execute(
            "SELECT batch_id, zip_filename, exported_count, skipped_count, package_mode FROM DerivativeExportBatches"
        ).fetchone()
        self.assertEqual(batch_row[0], result.batch_public_id)
        self.assertEqual(batch_row[1], Path(result.zip_path).name)
        self.assertEqual(Path(result.zip_path).name, "Authenticity Tests.zip")
        self.assertEqual(batch_row[2], 2)
        self.assertEqual(batch_row[3], 0)
        self.assertEqual(batch_row[4], "zip")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
            2,
        )

    def test_external_conversion_skips_metadata_watermark_and_derivative_registration(self):
        source_one = self.write_audio_fixture(
            "external-one.wav",
            duration_seconds=30,
            seed=20,
            suffix=".wav",
        )
        source_two = self.write_audio_fixture(
            "external-two.wav",
            duration_seconds=30,
            seed=21,
            suffix=".wav",
        )
        manifest_count_before = self.conn.execute(
            "SELECT COUNT(*) FROM AuthenticityManifests"
        ).fetchone()[0]
        derivative_count_before = self.conn.execute(
            "SELECT COUNT(*) FROM TrackAudioDerivatives"
        ).fetchone()[0]

        result = ExternalAudioConversionCoordinator(
            conversion_service=self.stub_conversion_service
        ).export(
            ExternalAudioConversionRequest(
                input_paths=[str(source_one), str(source_two)],
                output_dir=self.root / "external_exports",
                output_format="wav",
            )
        )

        self.assertEqual(result.exported, 2)
        self.assertIsNotNone(result.zip_path)
        self.assertTrue(
            all(call["metadata_behavior"] == "strip" for call in self.stub_conversion_service.calls)
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
            derivative_count_before,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM AuthenticityManifests").fetchone()[0],
            manifest_count_before,
        )
        with zipfile.ZipFile(result.zip_path) as archive:
            members = archive.namelist()
            self.assertEqual(len(members), 2)
            extract_root = Path(tempfile.mkdtemp())
            archive.extract(members[0], path=extract_root)
            extracted = extract_root / members[0]
        tags = self.audio_tag_service.read_tags(extracted)
        self.assertIsNone(tags.title)
        self.assertIsNone(tags.artist)
        self.assertIsNone(tags.album)
        self.assertIsNone(tags.album_artist)
        self.assertIsNone(tags.isrc)
        self.assertIsNone(tags.upc)

    def test_managed_export_reports_real_progress_stages_before_terminal_completion(self):
        track_id, _source_path = self.create_track_with_audio(
            title="Progress Managed Source",
            duration_seconds=30,
            seed=24,
            suffix=".wav",
        )
        progress_updates: list[tuple[int, int, str]] = []

        result = self._managed_coordinator().export(
            ManagedDerivativeExportRequest(
                track_ids=[track_id],
                output_dir=self.root / "managed_progress_exports",
                output_format="flac",
                derivative_kind=MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
                profile_name="Test Profile",
            ),
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(result.exported, 1)
        self.assertTrue(progress_updates)
        self.assertEqual(
            [value for value, _maximum, _message in progress_updates],
            sorted(value for value, _maximum, _message in progress_updates),
        )
        messages = [message for _value, _maximum, message in progress_updates]
        self.assertIn("Resolving source audio 1 of 1: Progress Managed Source", messages)
        self.assertIn("Converting derivative 1 of 1: Progress Managed Source", messages)
        self.assertIn("Applying direct watermark 1 of 1: Progress Managed Source", messages)
        self.assertIn("Writing catalog metadata 1 of 1: Progress Managed Source", messages)
        self.assertIn("Hashing finalized derivative 1 of 1: Progress Managed Source", messages)
        self.assertIn("Registering derivative 1 of 1: Progress Managed Source", messages)
        self.assertIn("Staging finalized derivative 1 of 1: Progress Managed Source", messages)
        self.assertIn("Finalizing managed derivative delivery…", messages)
        self.assertLess(progress_updates[-1][0], progress_updates[-1][1])
        self.assertTrue(all("finished" not in message.lower() for message in messages))

    def test_external_conversion_reports_real_progress_stages_before_terminal_completion(self):
        source = self.write_audio_fixture(
            "external-progress.wav",
            duration_seconds=30,
            seed=25,
            suffix=".wav",
        )
        progress_updates: list[tuple[int, int, str]] = []

        result = ExternalAudioConversionCoordinator(
            conversion_service=self.stub_conversion_service
        ).export(
            ExternalAudioConversionRequest(
                input_paths=[str(source)],
                output_dir=self.root / "external_progress_exports",
                output_format="wav",
            ),
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(result.exported, 1)
        self.assertEqual(
            [value for value, _maximum, _message in progress_updates],
            sorted(value for value, _maximum, _message in progress_updates),
        )
        self.assertEqual(
            [message for _value, _maximum, message in progress_updates],
            [
                "Converting external audio 1 of 1: external-progress.wav",
                "Finalizing converted output…",
            ],
        )
        self.assertLess(progress_updates[-1][0], progress_updates[-1][1])
        self.assertTrue(
            all("finished" not in message.lower() for _value, _maximum, message in progress_updates)
        )

    def test_audio_conversion_service_strip_metadata_mode_adds_ffmpeg_strip_flags(self):
        source = self.write_audio_fixture(
            "strip-metadata-source.wav",
            duration_seconds=5,
            seed=29,
            suffix=".wav",
        )
        destination = self.root / "strip-metadata-destination.wav"
        fake_ffmpeg = self.root / "ffmpeg"
        fake_ffmpeg.write_text("", encoding="utf-8")
        captured_commands: list[list[str]] = []

        def _fake_run(command, **_kwargs):
            captured_commands.append(list(command))
            Path(command[-1]).write_bytes(b"RIFF")
            return mock.Mock()

        with (
            mock.patch("isrc_manager.media.conversion.shutil.which", return_value=str(fake_ffmpeg)),
            mock.patch("isrc_manager.media.conversion.subprocess.run", side_effect=_fake_run),
        ):
            service = AudioConversionService()
            service.transcode(
                source_path=source,
                destination_path=destination,
                target_id="wav",
                metadata_behavior="strip",
            )

        self.assertEqual(len(captured_commands), 1)
        command = captured_commands[0]
        self.assertIn("-map_metadata", command)
        self.assertIn("-1", command)
        self.assertIn("-vn", command)
        self.assertIn("-sn", command)
        self.assertIn("-dn", command)

    def test_audio_conversion_service_reports_unavailable_without_ffmpeg(self):
        with (
            mock.patch("isrc_manager.media.conversion.shutil.which", return_value=None),
            mock.patch(
                "isrc_manager.media.conversion._ffmpeg_candidate_paths",
                return_value=tuple(),
            ),
        ):
            service = AudioConversionService()
        self.assertFalse(service.is_available())
        self.assertEqual(service.managed_target_ids(), tuple())
        self.assertEqual(service.managed_lossy_target_ids(), tuple())
        self.assertEqual(service.external_target_ids(), tuple())
        with self.assertRaises(RuntimeError):
            service.require_available()

    def test_audio_conversion_service_finds_common_ffmpeg_location_when_path_misses(self):
        fake_ffmpeg = self.root / "homebrew" / "bin" / "ffmpeg"
        fake_ffmpeg.parent.mkdir(parents=True)
        fake_ffmpeg.write_text("", encoding="utf-8")

        with (
            mock.patch("isrc_manager.media.conversion.shutil.which", return_value=None),
            mock.patch(
                "isrc_manager.media.conversion._ffmpeg_candidate_paths",
                return_value=(fake_ffmpeg,),
            ),
        ):
            service = AudioConversionService()

        self.assertTrue(service.is_available())
        self.assertEqual(service.ffmpeg_path(), fake_ffmpeg)

    def test_managed_lossy_target_profiles_exclude_raw_aac(self):
        self.assertEqual(
            tuple(profile.id for profile in managed_lossy_target_profiles()),
            ("mp3", "ogg", "opus", "m4a"),
        )

    def test_audio_conversion_service_reports_only_taggable_managed_lossy_targets(self):
        service = AudioConversionService(ffmpeg_path="/tmp/fake-ffmpeg")
        with mock.patch.object(service, "is_available", return_value=True):
            with mock.patch.object(service, "ffmpeg_path", return_value=Path("/tmp/fake-ffmpeg")):
                with mock.patch.object(
                    service,
                    "_load_encoders",
                    return_value={"libmp3lame", "libvorbis", "libopus", "aac"},
                ):
                    with mock.patch.object(
                        service,
                        "_managed_lossy_target_usable",
                        side_effect=lambda profile: profile.id in {"mp3", "ogg", "opus", "m4a"},
                    ):
                        caps = service.capabilities()
        self.assertEqual(
            tuple(profile.id for profile in caps.managed_targets),
            ("wav", "flac", "aiff"),
        )
        self.assertEqual(
            tuple(profile.id for profile in caps.managed_lossy_targets),
            ("mp3", "ogg", "opus", "m4a"),
        )
        self.assertEqual(
            tuple(profile.id for profile in caps.external_targets),
            ("wav", "flac", "aiff", "mp3", "ogg", "opus", "m4a", "aac"),
        )

    def test_audio_conversion_service_gates_external_targets_by_available_encoders(self):
        fake_ffmpeg = self.root / "ffmpeg"
        fake_ffmpeg.write_text("", encoding="utf-8")
        encoder_stdout = "\n".join(
            [
                " A..... flac             FLAC (Free Lossless Audio Codec)",
                " A..... libmp3lame       MP3 (MPEG audio layer 3)",
                " A..... libvorbis        Vorbis",
            ]
        )
        completed = mock.Mock(stdout=encoder_stdout)

        with (
            mock.patch("isrc_manager.media.conversion.shutil.which", return_value=str(fake_ffmpeg)),
            mock.patch("isrc_manager.media.conversion.subprocess.run", return_value=completed),
        ):
            service = AudioConversionService()
            self.assertTrue(service.is_available())
            self.assertEqual(service.managed_target_ids(), ("wav", "flac", "aiff"))
            self.assertEqual(service.external_target_ids(), ("wav", "flac", "aiff", "mp3", "ogg"))
            self.assertTrue(service.is_supported_target("mp3", managed_only=False))
            self.assertFalse(service.is_supported_target("mp3", managed_only=True))
            self.assertFalse(service.is_supported_target("opus", managed_only=False))


if __name__ == "__main__":
    unittest.main()

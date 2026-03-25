import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from isrc_manager.assets import AssetService
from isrc_manager.authenticity import (
    DOCUMENT_TYPE_DIRECT_WATERMARK,
    WORKFLOW_KIND_AUTHENTICITY_MASTER,
    AudioAuthenticityService,
    AudioWatermarkService,
    AuthenticityKeyService,
    AuthenticityManifestService,
)
from isrc_manager.forensics import ForensicExportCoordinator, ForensicWatermarkService
from isrc_manager.media import AudioConversionService
from isrc_manager.releases import ReleaseService
from isrc_manager.rights import RightsService
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.session import ProfileKVService
from isrc_manager.services.tracks import TrackCreatePayload, TrackService
from isrc_manager.tags import AudioTagService
from isrc_manager.works import WorkService


class AuthenticityWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.data_root = self.root / "data"
        self.settings_root = self.root / "settings"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.settings_root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.root / "catalog.db")
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()

        self.track_service = TrackService(self.conn, data_root=self.data_root)
        self.release_service = ReleaseService(self.conn)
        self.work_service = WorkService(self.conn)
        self.rights_service = RightsService(self.conn)
        self.asset_service = AssetService(self.conn, data_root=self.data_root)
        self.profile_kv = ProfileKVService(self.conn)
        self.audio_tag_service = AudioTagService()
        self.key_service = AuthenticityKeyService(
            self.conn,
            profile_kv=self.profile_kv,
            settings_root=self.settings_root,
        )
        self.default_key = self.key_service.generate_keypair(signer_label="Test Signer")
        self.manifest_service = AuthenticityManifestService(
            self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            work_service=self.work_service,
            rights_service=self.rights_service,
            asset_service=self.asset_service,
            key_service=self.key_service,
        )
        self.watermark_service = AudioWatermarkService()
        self.audio_service = AudioAuthenticityService(
            self.conn,
            key_service=self.key_service,
            manifest_service=self.manifest_service,
            watermark_service=self.watermark_service,
            tag_service=self.audio_tag_service,
            app_version="test-app",
        )
        self.forensic_watermark_service = ForensicWatermarkService()
        self.forensic_service = ForensicExportCoordinator(
            conn=self.conn,
            track_service=self.track_service,
            release_service=self.release_service,
            tag_service=self.audio_tag_service,
            key_service=self.key_service,
            conversion_service=AudioConversionService(),
            watermark_service=self.forensic_watermark_service,
        )
        self._track_counter = 0

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def create_track_with_audio(
        self,
        *,
        title: str = "Authenticity Track",
        artist_name: str = "Moonwake",
        album_title: str = "Authenticity Tests",
        duration_seconds: int = 30,
        seed: int = 1,
        suffix: str = ".wav",
        release_date: str = "2026-03-23",
        iswc: str | None = "T-123.456.789-Z",
        upc: str | None = "123456789012",
        genre: str | None = "Ambient",
        catalog_number: str | None = None,
        composer: str | None = None,
        publisher: str | None = None,
        comments: str | None = None,
        lyrics: str | None = None,
    ) -> tuple[int, Path]:
        self._track_counter += 1
        track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc=f"NL-TST-26-{self._track_counter:05d}",
                track_title=title,
                artist_name=artist_name,
                additional_artists=[],
                album_title=album_title,
                release_date=release_date,
                track_length_sec=int(duration_seconds),
                iswc=iswc,
                upc=upc,
                genre=genre,
                catalog_number=catalog_number or f"CAT-{self._track_counter:04d}",
                composer=composer,
                publisher=publisher,
                comments=comments,
                lyrics=lyrics,
            )
        )
        audio_path = self.write_audio_fixture(
            f"track-{track_id}{suffix}",
            duration_seconds=duration_seconds,
            seed=seed,
            suffix=suffix,
        )
        self.track_service.set_media_path(
            track_id,
            "audio_file",
            audio_path,
            storage_mode="managed_file",
        )
        return track_id, audio_path

    def write_audio_fixture(
        self,
        name: str,
        *,
        duration_seconds: int,
        seed: int,
        suffix: str,
    ) -> Path:
        sample_rate = 44100
        t = np.arange(sample_rate * duration_seconds, dtype=np.float32) / sample_rate
        rng = np.random.default_rng(seed)
        signal = (
            0.25 * np.sin(2 * np.pi * (180 + seed * 17) * t)
            + 0.18 * np.sin(2 * np.pi * (910 + seed * 13) * t)
            + 0.09 * np.sin(2 * np.pi * (2300 + seed * 31) * t)
            + 0.06 * np.sin(2 * np.pi * (4100 + seed * 19) * t)
        ).astype(np.float32)
        modulation = 1.0 + 0.25 * np.sin(2 * np.pi * 0.7 * t)
        signal *= modulation.astype(np.float32)
        signal += 0.02 * rng.standard_normal(signal.shape[0], dtype=np.float32)
        signal = np.clip(signal, -0.95, 0.95)
        stereo = np.stack([signal, np.roll(signal, 97)], axis=1)
        path = self.root / name
        clean_suffix = suffix.lower()
        if clean_suffix == ".flac":
            format_name = "FLAC"
            subtype = "PCM_24"
        elif clean_suffix in {".aif", ".aiff"}:
            format_name = "AIFF"
            subtype = "PCM_24"
        elif clean_suffix == ".mp3":
            format_name = "MP3"
            subtype = "MPEG_LAYER_III"
        elif clean_suffix in {".ogg", ".oga"}:
            format_name = "OGG"
            subtype = "VORBIS"
        elif clean_suffix == ".opus":
            format_name = "OGG"
            subtype = "OPUS"
        else:
            format_name = "WAV"
            subtype = "PCM_24"
        sf.write(path, stereo, sample_rate, format=format_name, subtype=subtype)
        return path

    def export_direct_authenticity_fixture(
        self,
        *,
        suffix: str = ".wav",
        duration_seconds: int = 30,
        seed: int = 1,
    ):
        track_id, audio_path = self.create_track_with_audio(
            duration_seconds=duration_seconds,
            seed=seed,
            suffix=suffix,
        )
        result = self.audio_service.export_watermarked_audio(
            output_dir=self.root / "exports",
            track_ids=[track_id],
            profile_name="Test Profile",
        )
        return track_id, audio_path, result

    def build_direct_sidecar(self, manifest_id: str) -> dict[str, object]:
        manifest_record = self.manifest_service.fetch_manifest_by_manifest_id(manifest_id)
        if manifest_record is None:
            raise AssertionError(f"Unknown manifest id: {manifest_id}")
        key_record = self.key_service.fetch_key(manifest_record.key_id)
        if key_record is None:
            raise AssertionError(f"Unknown key id: {manifest_record.key_id}")
        return {
            "schema_version": 1,
            "document_type": DOCUMENT_TYPE_DIRECT_WATERMARK,
            "workflow_kind": WORKFLOW_KIND_AUTHENTICITY_MASTER,
            "key_id": manifest_record.key_id,
            "payload": json.loads(manifest_record.payload_canonical),
            "signature_b64": manifest_record.signature_b64,
            "public_key_b64": key_record.public_key_b64,
            "payload_sha256": manifest_record.payload_sha256,
        }

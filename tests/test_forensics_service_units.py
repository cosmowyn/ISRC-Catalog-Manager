from __future__ import annotations

import sqlite3
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import isrc_manager.forensics.service as forensic_service_module
from isrc_manager.forensics.models import (
    FORENSIC_STATUS_MATCH_FOUND,
    FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
    FORENSIC_STATUS_NOT_DETECTED,
    FORENSIC_STATUS_TOKEN_UNRESOLVED,
    FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    ForensicExportRecord,
    ForensicExportRequest,
    ForensicWatermarkToken,
)
from isrc_manager.forensics.service import (
    ForensicExportCoordinator,
    ForensicLedgerService,
    ForensicWatermarkService,
    _batch_public_id,
    _binding_crc32,
    _clean_text,
    _final_audio_filename,
    _forensic_export_public_id,
    _package_dir_name,
    _package_zip_filename,
    _report_stage,
    _ResolutionCandidate,
    _sha256_for_file,
)


class _ContextConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _ConversionService:
    def __init__(self, *, supported: bool = True):
        self.supported = supported
        self.transcodes: list[tuple[Path, Path, str]] = []

    def is_supported_target(
        self,
        _format_id: str,
        *,
        managed_only: bool = False,
        capability_group: str | None = None,
    ) -> bool:
        return self.supported

    def transcode(self, *, source_path: Path, destination_path: Path, target_id: str) -> None:
        self.transcodes.append((Path(source_path), Path(destination_path), target_id))
        Path(destination_path).write_bytes(b"converted")


class _DerivativeLedger:
    def __init__(self):
        self.deleted_batches: list[str] = []
        self.completed_batches: list[tuple[str, str]] = []
        self.derivatives: list[dict[str, object]] = []

    def create_batch(self, **_kwargs) -> str:
        return "batch-row-1"

    def delete_batch(self, batch_id: str) -> None:
        self.deleted_batches.append(batch_id)

    def create_derivative(self, **kwargs) -> str:
        self.derivatives.append(kwargs)
        return f"derivative-{kwargs['source_track_id']}"

    def update_batch_completion(self, batch_id: str, **kwargs) -> None:
        self.completed_batches.append((batch_id, str(kwargs.get("package_mode"))))


class _TrackService:
    def __init__(self):
        self.snapshots: dict[int, object | None] = {}
        self.has_media_result = True
        self.handle = None

    def fetch_track_snapshot(self, track_id: int):
        return self.snapshots.get(track_id)

    def has_media(self, _track_id: int, _slot: str) -> bool:
        return self.has_media_result

    def resolve_media_source(self, _track_id: int, _slot: str):
        return self.handle


class _ForensicLedger:
    def __init__(self):
        self.token_record: ForensicExportRecord | None = None
        self.hash_record: ForensicExportRecord | None = None
        self.candidates: list[_ResolutionCandidate] = []
        self.verifications: list[tuple[str, str, float | None]] = []

    def fetch_by_token(self, _token_id: int, _binding_crc32: int) -> ForensicExportRecord | None:
        return self.token_record

    def fetch_by_output_sha256(self, _output_sha256: str) -> ForensicExportRecord | None:
        return self.hash_record

    def iter_resolution_candidates(self) -> list[_ResolutionCandidate]:
        return list(self.candidates)

    def create_export(self, *, track_id: int, **_kwargs) -> str:
        return f"fwx-{track_id}"

    def record_verification(
        self, forensic_export_id: str, *, status: str, confidence: float | None
    ) -> None:
        self.verifications.append((forensic_export_id, status, confidence))


class _SourceHandle:
    storage_mode = "managed_file"

    def __init__(self, source: Path, sha256: str = "source-sha"):
        self.source = source
        self._sha256 = sha256

    def sha256_hex(self) -> str:
        return self._sha256

    @contextmanager
    def materialize_path(self):
        yield self.source


def _record(**overrides) -> ForensicExportRecord:
    values = {
        "forensic_export_id": "fwx-1",
        "batch_id": "batch-1",
        "derivative_export_id": "derivative-1",
        "track_id": 42,
        "key_id": "key-1",
        "token_version": 1,
        "forensic_watermark_version": 1,
        "token_id": 77,
        "binding_crc32": 1234,
        "recipient_label": "Reviewer",
        "share_label": "Leak Trace",
        "output_format": "mp3",
        "output_filename": "Track.mp3",
        "output_sha256": None,
        "output_size_bytes": 100,
        "source_lineage_ref": "track-audio/42/source",
        "created_at": "2026-05-25T00:00:00Z",
    }
    values.update(overrides)
    return ForensicExportRecord(**values)


def _coordinator(tmp_path: Path) -> ForensicExportCoordinator:
    coordinator = ForensicExportCoordinator.__new__(ForensicExportCoordinator)
    coordinator.conn = _ContextConnection()
    coordinator.track_service = _TrackService()
    coordinator.release_service = None
    coordinator.tag_service = mock.Mock()
    coordinator.key_service = mock.Mock()
    coordinator.key_service.list_keys.return_value = []
    coordinator.key_service.default_key_id.return_value = None
    coordinator.conversion_service = _ConversionService()
    coordinator.watermark_service = mock.Mock()
    coordinator.derivative_ledger = _DerivativeLedger()
    coordinator.forensic_ledger = _ForensicLedger()
    coordinator._forensic_key_material = mock.Mock(return_value=("key-1", b"watermark-key"))
    return coordinator


def _ledger_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE ForensicWatermarkExports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forensic_export_id TEXT,
            batch_id TEXT,
            derivative_export_id TEXT,
            track_id INTEGER,
            key_id TEXT,
            token_version INTEGER,
            forensic_watermark_version INTEGER,
            token_id INTEGER,
            binding_crc32 INTEGER,
            recipient_label TEXT,
            share_label TEXT,
            output_format TEXT,
            output_filename TEXT,
            output_sha256 TEXT,
            output_size_bytes INTEGER,
            source_lineage_ref TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_verified_at TEXT,
            last_verification_status TEXT,
            last_verification_confidence REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE TrackAudioDerivatives(
            export_id TEXT PRIMARY KEY,
            source_audio_sha256 TEXT,
            source_lineage_ref TEXT
        )
        """
    )
    return conn


def test_forensic_service_helpers_normalize_names_hashes_and_progress(tmp_path: Path) -> None:
    source = tmp_path / "audio.bin"
    source.write_bytes(b"abc")
    progress: list[tuple[int, int, str]] = []

    assert _clean_text("  Reviewer  ") == "Reviewer"
    assert _clean_text("   ") is None
    assert _batch_public_id().startswith("FEX-")
    assert _forensic_export_public_id().startswith("FWX-")
    assert _sha256_for_file(source) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert _final_audio_filename("  Bad/Name?.wav") == "Name_.wav"
    assert _package_dir_name(None).startswith("Release")
    assert _package_zip_filename(["Album A", None]) == "Album A.zip"
    assert _binding_crc32(
        batch_id="batch",
        track_id=7,
        output_format="MP3",
        recipient_label="A",
        share_label="B",
    ) == _binding_crc32(
        batch_id="batch",
        track_id=7,
        output_format="mp3",
        recipient_label="A",
        share_label="B",
    )

    _report_stage(
        lambda value, maximum, message: progress.append((value, maximum, message)),
        item_index=2,
        item_total=3,
        stage_index=4,
        stage_count=9,
        message="Working",
    )
    _report_stage(None, item_index=1, item_total=1, stage_index=0, stage_count=1, message="noop")

    assert progress == [(13, 27, "Working")]


def test_forensic_ledger_round_trips_exports_candidates_and_verifications() -> None:
    conn = _ledger_connection()
    ledger = ForensicLedgerService(conn)
    token = ForensicWatermarkToken(version=1, token_id=55, binding_crc32=999)

    assert ledger._row_to_record(None) is None
    forensic_export_id = ledger.create_export(
        batch_id="batch-row-1",
        derivative_export_id="derivative-1",
        track_id=12,
        key_id="key-1",
        token=token,
        recipient_label=" Reviewer ",
        share_label=" Promo ",
        output_format=" MP3 ",
        output_filename="Track.mp3",
        output_sha256="output-sha",
        output_size_bytes=123,
        source_lineage_ref="track-audio/12/source-sha",
    )
    conn.execute(
        """
        INSERT INTO TrackAudioDerivatives(export_id, source_audio_sha256, source_lineage_ref)
        VALUES (?, ?, ?)
        """,
        ("derivative-1", "source-sha", "track-audio/12/source-sha"),
    )

    by_token = ledger.fetch_by_token(55, 999)
    by_hash = ledger.fetch_by_output_sha256("output-sha")
    candidates = ledger.iter_resolution_candidates()
    ledger.record_verification(
        forensic_export_id,
        status=FORENSIC_STATUS_MATCH_FOUND,
        confidence=0.875,
    )
    verification = conn.execute(
        """
        SELECT last_verification_status, last_verification_confidence
        FROM ForensicWatermarkExports
        WHERE forensic_export_id=?
        """,
        (forensic_export_id,),
    ).fetchone()

    assert by_token is not None
    assert by_token.forensic_export_id == forensic_export_id
    assert by_token.recipient_label == "Reviewer"
    assert by_token.output_format == "mp3"
    assert by_hash is not None
    assert by_hash.token_id == 55
    assert len(candidates) == 1
    assert candidates[0].record.forensic_export_id == forensic_export_id
    assert candidates[0].source_audio_sha256 == "source-sha"
    assert verification == (FORENSIC_STATUS_MATCH_FOUND, 0.875)
    conn.close()


def test_watermark_service_wrapper_delegates_core_operations(tmp_path: Path) -> None:
    token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=20)
    service = ForensicWatermarkService()
    service.core = mock.Mock()
    service.core.embed_to_path.return_value = {"snr_db": 12.5}
    service.core.extract_from_path.return_value = "extracted"
    service.core.verify_expected_token_against_reference.return_value = "verified"

    assert service.settings_payload()["token_bytes"] == 15
    assert service.embed_to_path(
        source_bytes=b"audio",
        destination_path=tmp_path / "out.wav",
        watermark_key=b"key",
        token=token,
    ) == {"snr_db": 12.5}
    assert service.extract_from_path(tmp_path / "out.wav", watermark_keys=[("key-1", b"k")])
    assert (
        service.verify_expected_token_against_reference(
            tmp_path / "candidate.wav",
            reference_bytes=b"reference",
            watermark_keys=[("key-1", b"k")],
            token=token,
        )
        == "verified"
    )


def test_embed_export_path_uses_direct_embedding_for_supported_delivery_path(
    tmp_path: Path,
) -> None:
    token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=20)
    service = ForensicWatermarkService()
    service.embed_to_path = mock.Mock(return_value={"frames": 5})
    conversion_service = _ConversionService()

    metrics = service.embed_export_path(
        source_path=tmp_path / "source.wav",
        destination_path=tmp_path / "dest.flac",
        output_format="flac",
        conversion_service=conversion_service,
        watermark_key=b"key",
        token=token,
    )

    assert metrics == {"frames": 5}
    service.embed_to_path.assert_called_once()
    assert conversion_service.transcodes == []


def test_embed_export_path_rejects_unsupported_delivery_format(tmp_path: Path) -> None:
    token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=20)
    service = ForensicWatermarkService()

    with pytest.raises(ValueError, match="Unsupported forensic delivery output format"):
        service.embed_export_path(
            source_path=tmp_path / "source.wav",
            destination_path=tmp_path / "dest.m4a",
            output_format="m4a",
            conversion_service=_ConversionService(),
            watermark_key=b"key",
            token=token,
        )


def test_embed_export_path_wraps_lossy_delivery_through_pcm(
    tmp_path: Path,
) -> None:
    token = ForensicWatermarkToken(version=1, token_id=10, binding_crc32=20)
    service = ForensicWatermarkService()
    service.embed_to_path = mock.Mock(return_value={"frames": 25})
    conversion_service = _ConversionService()

    metrics = service.embed_export_path(
        source_path=tmp_path / "source.flac",
        destination_path=tmp_path / "dest.mp3",
        output_format="MP3",
        conversion_service=conversion_service,
        watermark_key=b"key",
        token=token,
    )

    assert metrics == {"frames": 25}
    assert [target_id for *_paths, target_id in conversion_service.transcodes] == ["wav", "mp3"]
    service.embed_to_path.assert_called_once()


def test_coordinator_init_and_key_material_delegate_to_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_record = SimpleNamespace(key_id="primary")
    key_service = mock.Mock()
    key_service.signing_material.return_value = (key_record, b"private", b"authenticity")
    monkeypatch.setattr(
        forensic_service_module,
        "derive_forensic_watermark_key",
        lambda private_key: b"forensic-" + private_key,
    )

    coordinator = ForensicExportCoordinator(
        conn=_ContextConnection(),
        track_service=_TrackService(),
        release_service=None,
        tag_service=mock.Mock(),
        key_service=key_service,
        conversion_service=_ConversionService(),
        watermark_service=mock.Mock(),
    )

    assert coordinator._forensic_key_material("primary") == ("primary", b"forensic-private")
    key_service.signing_material.assert_called_once_with("primary")


def test_prepare_analysis_audio_converts_unsupported_files_and_rejects_without_decoder(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "candidate.mp3"
    source.write_bytes(b"mp3")

    analysis = coordinator._prepare_analysis_audio(source, tmp_path)

    assert analysis == tmp_path / "candidate.wav"
    assert analysis.read_bytes() == b"converted"
    assert coordinator.conversion_service.transcodes[-1] == (source, analysis, "wav")

    coordinator.conversion_service = _ConversionService(supported=False)
    with pytest.raises(ValueError, match="cannot be decoded"):
        coordinator._prepare_analysis_audio(source, tmp_path)


def test_forensic_extraction_keys_orders_default_and_skips_unloadable_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.key_service.list_keys.return_value = [
        SimpleNamespace(key_id="secondary"),
        SimpleNamespace(key_id="primary"),
        SimpleNamespace(key_id="broken"),
    ]
    coordinator.key_service.default_key_id.return_value = "primary"

    def load_private_key(key_id: str) -> bytes:
        if key_id == "broken":
            raise RuntimeError("missing private key")
        return key_id.encode()

    coordinator.key_service.load_private_key.side_effect = load_private_key
    monkeypatch.setattr(
        forensic_service_module,
        "derive_forensic_watermark_key",
        lambda private_key: b"derived-" + private_key,
    )

    assert coordinator._forensic_extraction_keys() == [
        ("primary", b"derived-primary"),
        ("secondary", b"derived-secondary"),
    ]


def test_rebuild_reference_audio_short_circuits_invalid_candidates(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    candidate = _ResolutionCandidate(
        record=_record(), source_audio_sha256="", source_lineage_ref=None
    )

    assert coordinator._rebuild_reference_audio(candidate=candidate, temp_dir=tmp_path) is None

    candidate = _ResolutionCandidate(
        record=_record(), source_audio_sha256="source-sha", source_lineage_ref=None
    )
    coordinator.track_service.has_media_result = False

    assert coordinator._rebuild_reference_audio(candidate=candidate, temp_dir=tmp_path) is None


def test_rebuild_reference_audio_rejects_hash_profile_mismatches_and_returns_supported_reference(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    coordinator.track_service.handle = _SourceHandle(source, sha256="actual-sha")

    wrong_hash = _ResolutionCandidate(
        record=_record(output_format="wav"),
        source_audio_sha256="expected-sha",
        source_lineage_ref=None,
    )
    assert coordinator._rebuild_reference_audio(candidate=wrong_hash, temp_dir=tmp_path) is None

    unknown_profile = _ResolutionCandidate(
        record=_record(output_format="not-a-format"),
        source_audio_sha256="actual-sha",
        source_lineage_ref=None,
    )
    assert (
        coordinator._rebuild_reference_audio(candidate=unknown_profile, temp_dir=tmp_path) is None
    )

    supported = _ResolutionCandidate(
        record=_record(output_format="wav"),
        source_audio_sha256="actual-sha",
        source_lineage_ref=None,
    )
    reference = coordinator._rebuild_reference_audio(candidate=supported, temp_dir=tmp_path)

    assert reference == tmp_path / "reference-fwx-1.wav"
    assert coordinator.conversion_service.transcodes == [(source, reference, "wav")]


def test_rebuild_reference_audio_transcodes_lossy_reference_to_analysis_wav(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")

    class _Handle:
        storage_mode = "managed_file"

        def sha256_hex(self) -> str:
            return "source-sha"

        @contextmanager
        def materialize_path(self):
            yield source

    coordinator.track_service.handle = _Handle()
    candidate = _ResolutionCandidate(
        record=_record(output_format="mp3"),
        source_audio_sha256="source-sha",
        source_lineage_ref="track-audio/42/source-sha",
    )

    reference = coordinator._rebuild_reference_audio(candidate=candidate, temp_dir=tmp_path)

    assert reference == tmp_path / "reference-fwx-1.wav"
    assert reference.read_bytes() == b"converted"
    assert coordinator.conversion_service.transcodes[-1][2] == "wav"


def test_export_with_no_attached_audio_deletes_empty_batch_and_reports_skip(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.track_service.snapshots = {101: None}

    result = coordinator.export(
        ForensicExportRequest(
            track_ids=[101],
            output_dir=str(tmp_path / "exports"),
            output_format="mp3",
            profile_name="Unit Profile",
        )
    )

    assert result.requested == 1
    assert result.exported == 0
    assert result.skipped == 1
    assert result.warnings == ["Track 101 has no attached audio."]
    assert coordinator.derivative_ledger.deleted_batches == ["batch-row-1"]


def test_export_single_track_finalizes_directory_and_records_metadata_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    coordinator.track_service.snapshots = {
        101: SimpleNamespace(track_title="Forensic Unit", album_title="Unit Album")
    }
    coordinator.track_service.handle = _SourceHandle(source)

    def embed_export_path(**kwargs) -> dict[str, int]:
        Path(kwargs["destination_path"]).write_bytes(b"watermarked")
        return {"frames": 10}

    coordinator.watermark_service.embed_export_path.side_effect = embed_export_path
    monkeypatch.setattr(
        forensic_service_module,
        "write_catalog_export_tags",
        lambda *_args, **_kwargs: (False, "tags unavailable"),
    )

    result = coordinator.export(
        ForensicExportRequest(
            track_ids=[101],
            output_dir=str(tmp_path / "exports"),
            output_format="mp3",
            recipient_label="Reviewer",
            share_label="Unit",
            profile_name="Unit Profile",
        )
    )

    assert result.exported == 1
    assert result.skipped == 0
    assert result.written_paths == [str(tmp_path / "exports" / "Unit Album" / "Forensic Unit.mp3")]
    assert Path(result.written_paths[0]).read_bytes() == b"watermarked"
    assert result.derivative_ids == ["derivative-101"]
    assert result.forensic_export_ids == ["fwx-101"]
    assert result.warnings == ["Forensic Unit: metadata embedding skipped; tags unavailable."]
    assert coordinator.derivative_ledger.completed_batches == [("batch-row-1", "directory")]


def test_export_multiple_tracks_packages_zip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    coordinator.track_service.snapshots = {
        101: SimpleNamespace(track_title="First", album_title="Unit Album"),
        102: SimpleNamespace(track_title="Second", album_title="Unit Album"),
    }
    coordinator.track_service.handle = _SourceHandle(source)

    def embed_export_path(**kwargs) -> dict[str, int]:
        Path(kwargs["destination_path"]).write_bytes(
            f"watermarked-{Path(kwargs['destination_path']).name}".encode()
        )
        return {"frames": 10}

    coordinator.watermark_service.embed_export_path.side_effect = embed_export_path
    monkeypatch.setattr(
        forensic_service_module,
        "write_catalog_export_tags",
        lambda *_args, **_kwargs: (True, None),
    )

    result = coordinator.export(
        ForensicExportRequest(
            track_ids=[101, 102],
            output_dir=str(tmp_path / "exports"),
            output_format="mp3",
        )
    )

    assert result.exported == 2
    assert result.zip_path == str(tmp_path / "exports" / "Unit Album.zip")
    assert result.written_paths == [result.zip_path]
    with zipfile.ZipFile(result.zip_path) as archive:
        assert sorted(archive.namelist()) == [
            "Unit Album/First.mp3",
            "Unit Album/Second.mp3",
        ]
    assert coordinator.derivative_ledger.completed_batches == [("batch-row-1", "zip")]


def test_export_rejects_target_when_conversion_service_lacks_forensic_capability(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.conversion_service = _ConversionService(supported=False)

    with pytest.raises(ValueError, match="Unsupported forensic watermark target"):
        coordinator.export(
            ForensicExportRequest(
                track_ids=[1],
                output_dir=str(tmp_path / "exports"),
                output_format="mp3",
            )
        )


def test_export_rejects_unknown_format_before_opening_batch(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)

    with pytest.raises(ValueError, match="Unsupported forensic output format"):
        coordinator.export(
            ForensicExportRequest(
                track_ids=[1],
                output_dir=str(tmp_path / "exports"),
                output_format="not-a-format",
            )
        )


def test_export_cancellation_raises_before_track_processing(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.track_service.snapshots = {
        101: SimpleNamespace(track_title="Cancelled", album_title="Cancelled Album")
    }

    with pytest.raises(InterruptedError, match="cancelled"):
        coordinator.export(
            ForensicExportRequest(
                track_ids=[101],
                output_dir=str(tmp_path / "exports"),
                output_format="mp3",
            ),
            is_cancelled=lambda: True,
        )


def test_export_cancellation_raises_after_source_materializes(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    coordinator.track_service.snapshots = {
        101: SimpleNamespace(track_title="Cancelled", album_title="Cancelled Album")
    }
    coordinator.track_service.handle = _SourceHandle(source)
    cancellation_checks = iter([False, True])

    with pytest.raises(InterruptedError, match="cancelled"):
        coordinator.export(
            ForensicExportRequest(
                track_ids=[101],
                output_dir=str(tmp_path / "exports"),
                output_format="mp3",
            ),
            is_cancelled=lambda: next(cancellation_checks),
        )


def test_export_removes_written_paths_when_completion_update_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    coordinator = _coordinator(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    coordinator.track_service.snapshots = {
        101: SimpleNamespace(track_title="Cleanup", album_title="Cleanup Album")
    }
    coordinator.track_service.handle = _SourceHandle(source)

    def embed_export_path(**kwargs) -> dict[str, int]:
        Path(kwargs["destination_path"]).write_bytes(b"watermarked")
        return {"frames": 10}

    coordinator.watermark_service.embed_export_path.side_effect = embed_export_path
    coordinator.derivative_ledger.update_batch_completion = mock.Mock(
        side_effect=RuntimeError("completion failed")
    )
    monkeypatch.setattr(
        forensic_service_module,
        "write_catalog_export_tags",
        lambda *_args, **_kwargs: (True, None),
    )

    final_path = tmp_path / "exports" / "Cleanup Album" / "Cleanup.mp3"
    with pytest.raises(RuntimeError, match="completion failed"):
        coordinator.export(
            ForensicExportRequest(
                track_ids=[101],
                output_dir=str(tmp_path / "exports"),
                output_format="mp3",
            )
        )

    assert not final_path.exists()


def test_inspect_file_rejects_missing_path(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)

    with pytest.raises(FileNotFoundError):
        coordinator.inspect_file(tmp_path / "missing.wav")


def test_inspect_file_reports_decode_failure(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    coordinator._prepare_analysis_audio = mock.Mock(side_effect=ValueError("decode failed"))

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT
    assert report.resolution_basis == "decode_failure"


def test_inspect_file_reports_blind_token_match_and_records_verification(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    token = ForensicWatermarkToken(version=1, token_id=77, binding_crc32=1234)
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(
        token=token,
        status="weak",
        mean_confidence=0.66,
    )
    coordinator.forensic_ledger.token_record = _record()

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_MATCH_LOW_CONFIDENCE
    assert report.resolution_basis == "blind_forensic_token"
    assert report.token_id == 77
    assert report.recipient_label == "Reviewer"
    assert coordinator.forensic_ledger.verifications == [
        ("fwx-1", FORENSIC_STATUS_MATCH_LOW_CONFIDENCE, 0.66)
    ]


def test_inspect_file_reports_unresolved_extracted_token(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    token = ForensicWatermarkToken(version=1, token_id=77, binding_crc32=1234)
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(
        token=token,
        status="detected",
        mean_confidence=0.81,
    )

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_TOKEN_UNRESOLVED
    assert report.token_id == 77
    assert "Binding CRC32: 1234" in report.details


def test_inspect_file_reports_exact_hash_match(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator.forensic_ledger.hash_record = _record(output_sha256="unused")

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_MATCH_FOUND
    assert report.resolution_basis == "exact_output_hash"
    assert report.exact_hash_match is True
    assert coordinator.forensic_ledger.verifications == [
        ("fwx-1", FORENSIC_STATUS_MATCH_FOUND, 1.0)
    ]


def test_inspect_file_uses_reference_guided_detected_match(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    reference = tmp_path / "reference.wav"
    inspected.write_bytes(b"candidate")
    reference.write_bytes(b"reference")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator.watermark_service.verify_expected_token_against_reference.return_value = (
        SimpleNamespace(
            status="detected",
            mean_confidence=0.91,
            group_agreement=0.88,
            sync_score=0.86,
        )
    )
    coordinator._rebuild_reference_audio = mock.Mock(return_value=reference)
    coordinator.forensic_ledger.candidates = [
        _ResolutionCandidate(
            record=_record(),
            source_audio_sha256="source-sha",
            source_lineage_ref="track-audio/42/source-sha",
        )
    ]

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_MATCH_FOUND
    assert report.resolution_basis == "reference_guided_forensic"
    assert report.exact_hash_match is False
    assert coordinator.forensic_ledger.verifications == [
        ("fwx-1", FORENSIC_STATUS_MATCH_FOUND, 0.91)
    ]


def test_inspect_file_skips_candidate_when_reference_verification_raises(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    reference = tmp_path / "reference.wav"
    inspected.write_bytes(b"candidate")
    reference.write_bytes(b"reference")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator._rebuild_reference_audio = mock.Mock(return_value=reference)
    coordinator._forensic_key_material = mock.Mock(side_effect=RuntimeError("key missing"))
    coordinator.forensic_ledger.candidates = [
        _ResolutionCandidate(
            record=_record(),
            source_audio_sha256="source-sha",
            source_lineage_ref="track-audio/42/source-sha",
        )
    ]

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_NOT_DETECTED
    assert report.resolution_basis == "no_match"


def test_inspect_file_returns_best_low_confidence_reference_candidate(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    reference = tmp_path / "reference.wav"
    inspected.write_bytes(b"candidate")
    reference.write_bytes(b"reference")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator._rebuild_reference_audio = mock.Mock(return_value=reference)
    coordinator.forensic_ledger.candidates = [
        _ResolutionCandidate(
            record=_record(forensic_export_id="weak", key_id="weak-key"),
            source_audio_sha256="weak-sha",
            source_lineage_ref=None,
        ),
        _ResolutionCandidate(
            record=_record(forensic_export_id="better", key_id="better-key"),
            source_audio_sha256="better-sha",
            source_lineage_ref=None,
        ),
    ]
    coordinator.watermark_service.verify_expected_token_against_reference.side_effect = [
        SimpleNamespace(
            status="insufficient",
            mean_confidence=0.30,
            group_agreement=0.40,
            sync_score=0.50,
        ),
        SimpleNamespace(
            status="insufficient",
            mean_confidence=0.72,
            group_agreement=0.65,
            sync_score=0.60,
        ),
    ]

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_MATCH_LOW_CONFIDENCE
    assert report.forensic_export_id == "better"
    assert "Sync Score: 0.600" in report.details
    assert coordinator.forensic_ledger.verifications == [
        ("better", FORENSIC_STATUS_MATCH_LOW_CONFIDENCE, 0.72)
    ]


def test_inspect_file_handles_reference_rebuild_failures_and_reports_no_match(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator._rebuild_reference_audio = mock.Mock(side_effect=RuntimeError("bad reference"))
    coordinator.forensic_ledger.candidates = [
        _ResolutionCandidate(
            record=_record(),
            source_audio_sha256="source-sha",
            source_lineage_ref="track-audio/42/source-sha",
        )
    ]

    report = coordinator.inspect_file(inspected)

    assert report.status == FORENSIC_STATUS_NOT_DETECTED
    assert report.resolution_basis == "no_match"


def test_inspect_file_can_be_cancelled_during_reference_comparison(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    inspected = tmp_path / "candidate.wav"
    inspected.write_bytes(b"candidate")
    coordinator.watermark_service.extract_from_path.return_value = SimpleNamespace(token=None)
    coordinator.forensic_ledger.candidates = [
        _ResolutionCandidate(
            record=_record(),
            source_audio_sha256="source-sha",
            source_lineage_ref="track-audio/42/source-sha",
        )
    ]

    with pytest.raises(InterruptedError, match="inspection cancelled"):
        coordinator.inspect_file(inspected, is_cancelled=lambda: True)

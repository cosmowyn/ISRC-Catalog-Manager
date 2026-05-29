from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from isrc_manager.integrations.soundcloud.media import (
    SoundCloudUploadMediaError,
    SoundCloudWatermarkedWavMediaPreparer,
)


class FakeMediaHandle:
    def __init__(
        self,
        *,
        filename: str,
        data: bytes | None = None,
        source_path: Path | None = None,
        mime_type: str | None = None,
    ) -> None:
        self.filename = filename
        self.suffix = Path(filename).suffix
        self.mime_type = mime_type
        self.source_path = source_path
        self.source_bytes = data
        self.size_bytes = len(data or b"") if source_path is None else source_path.stat().st_size
        self.materialized = 0

    @contextmanager
    def materialize_path(self):
        self.materialized += 1
        if self.source_path is not None:
            yield self.source_path
            return
        suffix = self.suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(bytes(self.source_bytes or b""))
            path = Path(handle.name)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class FakeTrackService:
    def __init__(self, handles: dict[str, FakeMediaHandle]) -> None:
        self.handles = handles
        self.calls: list[tuple[int, str]] = []

    def resolve_media_source(self, track_id: int, media_key: str) -> FakeMediaHandle:
        self.calls.append((track_id, media_key))
        handle = self.handles.get(media_key)
        if handle is None:
            raise FileNotFoundError(media_key)
        return handle


class FakeConversionService:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[tuple[Path, Path, str, str]] = []

    def is_available(self) -> bool:
        return self.available

    def transcode(
        self,
        *,
        source_path,
        destination_path,
        target_id,
        metadata_behavior="inherit",
    ):
        source = Path(source_path)
        destination = Path(destination_path)
        self.calls.append((source, destination, str(target_id), str(metadata_behavior)))
        destination.write_bytes(source.read_bytes() + b"-converted-wav")
        return SimpleNamespace(destination_path=destination, output_format=target_id)


class FakeAuthenticityService:
    def __init__(self, *, fail: bool = False, write_output: bool = True) -> None:
        self.fail = fail
        self.write_output = write_output
        self.calls: list[tuple[int, Path, Path, str | None]] = []

    def watermark_catalog_derivative(
        self,
        *,
        track_id,
        source_path,
        destination_path,
        profile_name=None,
        **_kwargs,
    ):
        source = Path(source_path)
        destination = Path(destination_path)
        self.calls.append((int(track_id), source, destination, profile_name))
        if self.fail:
            raise RuntimeError("watermark failed")
        if self.write_output:
            destination.write_bytes(source.read_bytes() + b"-watermarked")
        return SimpleNamespace(manifest_id="manifest-1")


def test_prepare_upload_media_materializes_blob_converts_to_watermarked_wav_and_artwork() -> None:
    track_service = FakeTrackService(
        {
            "audio_file": FakeMediaHandle(
                filename="../../Forest Mix.flac",
                data=b"embedded-audio",
                mime_type="audio/flac",
            ),
            "album_art": FakeMediaHandle(
                filename="cover.png",
                data=b"embedded-artwork",
                mime_type="image/png",
            ),
        }
    )
    conversion = FakeConversionService()
    authenticity = FakeAuthenticityService()
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=track_service,
        authenticity_service=authenticity,
        conversion_service=conversion,
        profile_name="Profile One",
    )

    prepared = preparer.prepare_upload_media(46, include_artwork=True)
    temp_root = prepared.audio_path.parent
    try:
        assert prepared.audio_path.name == "Forest_Mix.soundcloud-watermarked.wav"
        assert prepared.audio_path.read_bytes() == b"embedded-audio-converted-wav-watermarked"
        assert prepared.artwork_path is not None
        assert prepared.artwork_path.read_bytes() == b"embedded-artwork"
        assert conversion.calls[0][2:] == ("wav", "strip")
        assert authenticity.calls[0][0] == 46
        assert authenticity.calls[0][3] == "Profile One"
        assert prepared.audio_sha256
    finally:
        prepared.cleanup()
    assert not temp_root.exists()


def test_prepare_upload_media_uses_existing_source_path_and_skips_artwork_when_not_requested(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"path-audio")
    track_service = FakeTrackService(
        {"audio_file": FakeMediaHandle(filename="source.wav", source_path=source)}
    )
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=track_service,
        authenticity_service=FakeAuthenticityService(),
        conversion_service=FakeConversionService(),
    )

    prepared = preparer.prepare_upload_media(7, include_artwork=False)
    try:
        assert prepared.artwork_path is None
        assert track_service.calls == [(7, "audio_file")]
    finally:
        prepared.cleanup()


def test_prepare_upload_media_allows_missing_artwork_when_audio_is_ready() -> None:
    track_service = FakeTrackService(
        {"audio_file": FakeMediaHandle(filename="source.wav", data=b"audio")}
    )
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=track_service,
        authenticity_service=FakeAuthenticityService(),
        conversion_service=FakeConversionService(),
    )

    prepared = preparer.prepare_upload_media(8, include_artwork=True)
    try:
        assert prepared.artwork_path is None
        assert track_service.calls == [(8, "audio_file"), (8, "album_art")]
    finally:
        prepared.cleanup()


def test_prepare_upload_media_requires_authenticity_watermark_service() -> None:
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=FakeTrackService(
            {"audio_file": FakeMediaHandle(filename="source.wav", data=b"audio")}
        ),
        authenticity_service=None,
        conversion_service=FakeConversionService(),
    )

    with pytest.raises(SoundCloudUploadMediaError, match="watermark support"):
        preparer.prepare_upload_media(1, include_artwork=False)


def test_prepare_upload_media_requires_ffmpeg_conversion() -> None:
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=FakeTrackService(
            {"audio_file": FakeMediaHandle(filename="source.wav", data=b"audio")}
        ),
        authenticity_service=FakeAuthenticityService(),
        conversion_service=FakeConversionService(available=False),
    )

    with pytest.raises(SoundCloudUploadMediaError, match="ffmpeg"):
        preparer.prepare_upload_media(1, include_artwork=False)


def test_prepare_upload_media_rejects_missing_audio_source() -> None:
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=FakeTrackService({}),
        authenticity_service=FakeAuthenticityService(),
        conversion_service=FakeConversionService(),
    )

    with pytest.raises(SoundCloudUploadMediaError, match="source audio"):
        preparer.prepare_upload_media(1, include_artwork=False)


def test_prepare_upload_media_cleans_temporary_files_when_watermark_fails() -> None:
    authenticity = FakeAuthenticityService(fail=True)
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=FakeTrackService(
            {"audio_file": FakeMediaHandle(filename="source.wav", data=b"audio")}
        ),
        authenticity_service=authenticity,
        conversion_service=FakeConversionService(),
    )

    with pytest.raises(RuntimeError, match="watermark failed"):
        preparer.prepare_upload_media(1, include_artwork=False)

    failed_destination = authenticity.calls[0][2]
    assert not failed_destination.parent.exists()


def test_prepare_upload_media_rejects_missing_watermarked_output_and_cleans_tempdir() -> None:
    authenticity = FakeAuthenticityService(write_output=False)
    preparer = SoundCloudWatermarkedWavMediaPreparer(
        track_service=FakeTrackService(
            {"audio_file": FakeMediaHandle(filename="source.wav", data=b"audio")}
        ),
        authenticity_service=authenticity,
        conversion_service=FakeConversionService(),
    )

    with pytest.raises(SoundCloudUploadMediaError, match="was not created"):
        preparer.prepare_upload_media(1, include_artwork=False)

    failed_destination = authenticity.calls[0][2]
    assert not failed_destination.parent.exists()

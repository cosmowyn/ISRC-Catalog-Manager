"""SoundCloud upload media preparation.

This module keeps SoundCloud uploads on the safe managed-export path:
source catalog audio is materialized from either managed files or database
blobs, transcoded to WAV, then watermarked before the API client receives an
upload path.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from isrc_manager.media import AudioConversionService


class SoundCloudUploadMediaError(RuntimeError):
    """Raised when a SoundCloud upload asset cannot be prepared safely."""


class _MaterializableMediaHandle(Protocol):
    filename: str
    suffix: str
    mime_type: str | None
    size_bytes: int
    source_path: Path | None

    def materialize_path(self) -> AbstractContextManager[Path]: ...


@dataclass(slots=True)
class SoundCloudPreparedUploadMedia:
    """Temporary media assets prepared for one upload item."""

    audio_path: Path
    artwork_path: Path | None
    audio_sha256: str
    _temp_dir: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> None:
        self._temp_dir.cleanup()


def _safe_stem(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    stem = Path(text).stem if text else ""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return clean[:96] or fallback


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SoundCloudWatermarkedWavMediaPreparer:
    """Prepare SoundCloud upload assets from catalog media.

    The returned audio path is always a freshly generated, watermarked WAV.
    The clean source path is never passed to the SoundCloud API client.
    """

    def __init__(
        self,
        *,
        track_service: Any,
        authenticity_service: Any,
        conversion_service: Any | None = None,
        profile_name: str | None = None,
    ) -> None:
        self.track_service = track_service
        self.authenticity_service = authenticity_service
        self.conversion_service = conversion_service or AudioConversionService()
        self.profile_name = str(profile_name or "").strip() or None

    def prepare_upload_media(
        self,
        track_id: int,
        *,
        include_artwork: bool,
    ) -> SoundCloudPreparedUploadMedia:
        if self.authenticity_service is None:
            raise SoundCloudUploadMediaError(
                "SoundCloud upload requires audio authenticity watermark support."
            )
        if not self.conversion_service.is_available():
            raise SoundCloudUploadMediaError(
                "SoundCloud upload requires ffmpeg to create a watermarked WAV file."
            )

        try:
            source_handle = self.track_service.resolve_media_source(track_id, "audio_file")
        except FileNotFoundError as exc:
            raise SoundCloudUploadMediaError(
                "SoundCloud upload source audio is unavailable."
            ) from exc

        temp_dir = tempfile.TemporaryDirectory(prefix=f"soundcloud-upload-{int(track_id)}-")
        temp_root = Path(temp_dir.name)
        base_name = _safe_stem(
            getattr(source_handle, "filename", "") or f"track-{int(track_id)}",
            f"track-{int(track_id)}",
        )
        converted_path = temp_root / f"{base_name}.soundcloud-source.wav"
        watermarked_path = temp_root / f"{base_name}.soundcloud-watermarked.wav"
        artwork_path: Path | None = None

        try:
            with source_handle.materialize_path() as materialized_source:
                self.conversion_service.transcode(
                    source_path=materialized_source,
                    destination_path=converted_path,
                    target_id="wav",
                    metadata_behavior="strip",
                )
            self.authenticity_service.watermark_catalog_derivative(
                track_id=int(track_id),
                source_path=converted_path,
                destination_path=watermarked_path,
                profile_name=self.profile_name,
            )
            if not watermarked_path.exists():
                raise SoundCloudUploadMediaError("SoundCloud watermarked WAV was not created.")
            if include_artwork:
                artwork_path = self._materialize_artwork(int(track_id), temp_root)
            return SoundCloudPreparedUploadMedia(
                audio_path=watermarked_path,
                artwork_path=artwork_path,
                audio_sha256=_sha256_for_file(watermarked_path),
                _temp_dir=temp_dir,
            )
        except Exception:
            temp_dir.cleanup()
            raise

    def _materialize_artwork(self, track_id: int, temp_root: Path) -> Path | None:
        try:
            artwork_handle = self.track_service.resolve_media_source(track_id, "album_art")
        except FileNotFoundError:
            return None
        source_path = Path(getattr(artwork_handle, "source_path", "") or "")
        suffix = Path(str(getattr(artwork_handle, "filename", "") or "")).suffix
        if not suffix and source_path.name:
            suffix = source_path.suffix
        suffix = suffix or ".artwork"
        destination = temp_root / f"track-{int(track_id)}-artwork{suffix}"
        with artwork_handle.materialize_path() as materialized_artwork:
            destination.write_bytes(Path(materialized_artwork).read_bytes())
        return destination

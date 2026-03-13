"""Helpers for validating and reading media files stored as blobs."""

import mimetypes
from functools import lru_cache
from pathlib import Path

from ..constants import BLOB_AUDIO_EXTS, BLOB_IMAGE_EXTS, MAX_BLOB_BYTES


def _ext(p: str) -> str:
    return Path(p).suffix.lower()


@lru_cache(maxsize=256)
def _guess_mime(p: str) -> str:
    mime, _ = mimetypes.guess_type(p)
    return mime or ""


def _is_valid_image_path(p: str) -> bool:
    return _ext(p) in BLOB_IMAGE_EXTS or _guess_mime(p).startswith("image/")


def _is_valid_audio_path(p: str) -> bool:
    return _ext(p) in BLOB_AUDIO_EXTS or _guess_mime(p).startswith("audio/")


def _read_blob_from_path(path: str) -> bytes:
    data = Path(path).read_bytes()
    if len(data) > MAX_BLOB_BYTES:
        raise ValueError(f"Selected file is too large (> {MAX_BLOB_BYTES} bytes)")
    return data

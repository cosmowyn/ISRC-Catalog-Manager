"""Canonical audio format descriptors and lossy/lossless helpers."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

_AUTHENTICITY_SAFE_SUFFIXES = frozenset({".wav", ".flac", ".aif", ".aiff"})
_FORENSIC_LOSSY_FORMAT_IDS = frozenset({"mp3"})
_MANAGED_LOSSY_FORMAT_IDS = frozenset({"mp3", "ogg", "opus", "m4a"})


@dataclass(frozen=True, slots=True)
class AudioFormatProfile:
    id: str
    label: str
    suffixes: tuple[str, ...]
    mime_types: tuple[str, ...]
    lossy: bool


_AUDIO_FORMAT_PROFILES: tuple[AudioFormatProfile, ...] = (
    AudioFormatProfile(
        id="wav",
        label="WAV",
        suffixes=(".wav",),
        mime_types=("audio/wav", "audio/x-wav", "audio/wave"),
        lossy=False,
    ),
    AudioFormatProfile(
        id="flac",
        label="FLAC",
        suffixes=(".flac",),
        mime_types=("audio/flac", "audio/x-flac"),
        lossy=False,
    ),
    AudioFormatProfile(
        id="aiff",
        label="AIFF",
        suffixes=(".aiff", ".aif"),
        mime_types=("audio/aiff", "audio/x-aiff"),
        lossy=False,
    ),
    AudioFormatProfile(
        id="mp3",
        label="MP3",
        suffixes=(".mp3",),
        mime_types=("audio/mpeg",),
        lossy=True,
    ),
    AudioFormatProfile(
        id="ogg",
        label="OGG",
        suffixes=(".ogg", ".oga"),
        mime_types=("audio/ogg", "application/ogg"),
        lossy=True,
    ),
    AudioFormatProfile(
        id="opus",
        label="Opus",
        suffixes=(".opus",),
        mime_types=("audio/opus",),
        lossy=True,
    ),
    AudioFormatProfile(
        id="m4a",
        label="M4A",
        suffixes=(".m4a", ".mp4"),
        mime_types=("audio/mp4", "video/mp4"),
        lossy=True,
    ),
    AudioFormatProfile(
        id="aac",
        label="AAC",
        suffixes=(".aac",),
        mime_types=("audio/aac", "audio/x-aac"),
        lossy=True,
    ),
)

_PROFILE_BY_ID = {profile.id: profile for profile in _AUDIO_FORMAT_PROFILES}
_PROFILE_BY_SUFFIX = {
    suffix: profile for profile in _AUDIO_FORMAT_PROFILES for suffix in profile.suffixes
}
_PROFILE_BY_MIME = {
    mime_type.casefold(): profile
    for profile in _AUDIO_FORMAT_PROFILES
    for mime_type in profile.mime_types
}


def audio_format_profiles() -> tuple[AudioFormatProfile, ...]:
    return _AUDIO_FORMAT_PROFILES


def audio_format_profile(format_id: str | None) -> AudioFormatProfile | None:
    clean_id = str(format_id or "").strip().lower()
    if not clean_id:
        return None
    return _PROFILE_BY_ID.get(clean_id)


def classify_audio_format(
    path_or_name: str | Path | None = None,
    *,
    mime_type: str | None = None,
) -> AudioFormatProfile | None:
    clean_mime = str(mime_type or "").strip().casefold()
    if clean_mime:
        profile = _PROFILE_BY_MIME.get(clean_mime)
        if profile is not None:
            return profile

    if path_or_name is None:
        return None
    suffix = Path(str(path_or_name)).suffix.strip().lower()
    if suffix:
        profile = _PROFILE_BY_SUFFIX.get(suffix)
        if profile is not None:
            return profile

    guessed_mime, _encoding = mimetypes.guess_type(str(path_or_name))
    if guessed_mime:
        return _PROFILE_BY_MIME.get(guessed_mime.casefold())
    return None


def is_lossy_audio_format(
    path_or_name: str | Path | None = None,
    *,
    mime_type: str | None = None,
) -> bool:
    profile = classify_audio_format(path_or_name, mime_type=mime_type)
    return bool(profile.lossy) if profile is not None else False


def format_label_for_audio(
    path_or_name: str | Path | None = None,
    *,
    mime_type: str | None = None,
) -> str | None:
    profile = classify_audio_format(path_or_name, mime_type=mime_type)
    return profile.label if profile is not None else None


def authenticity_safe_target_profiles() -> tuple[AudioFormatProfile, ...]:
    return tuple(
        profile
        for profile in _AUDIO_FORMAT_PROFILES
        if profile.suffixes and profile.suffixes[0] in _AUTHENTICITY_SAFE_SUFFIXES
    )


def forensic_target_profiles() -> tuple[AudioFormatProfile, ...]:
    return tuple(
        profile for profile in _AUDIO_FORMAT_PROFILES if profile.id in _FORENSIC_LOSSY_FORMAT_IDS
    )


def managed_derivative_target_profiles() -> tuple[AudioFormatProfile, ...]:
    # Backwards-compatible alias for the watermark-safe managed branch.
    return authenticity_safe_target_profiles()


def managed_lossy_target_profiles() -> tuple[AudioFormatProfile, ...]:
    return tuple(
        profile for profile in _AUDIO_FORMAT_PROFILES if profile.id in _MANAGED_LOSSY_FORMAT_IDS
    )

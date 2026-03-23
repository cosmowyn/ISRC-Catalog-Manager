"""ffmpeg-backed audio conversion helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from isrc_manager.tags import AudioTagData, AudioTagService

from .audio_formats import (
    AudioFormatProfile,
    audio_format_profiles,
    forensic_target_profiles,
    managed_derivative_target_profiles,
    managed_lossy_target_profiles,
)

_ENCODER_LINE_PATTERN = re.compile(r"^\s*[A-Z\.]{6}\s+([^\s]+)")


@dataclass(frozen=True, slots=True)
class _TranscodeTargetConfig:
    args: tuple[str, ...]
    codec_name: str | None
    encoder_names: tuple[str, ...] = ()


_TRANSCODE_TARGETS: dict[str, _TranscodeTargetConfig] = {
    "wav": _TranscodeTargetConfig(args=("-c:a", "pcm_s24le"), codec_name="pcm_s24le"),
    "flac": _TranscodeTargetConfig(args=("-c:a", "flac"), codec_name="flac"),
    "aiff": _TranscodeTargetConfig(args=("-c:a", "pcm_s24be"), codec_name="pcm_s24be"),
    "mp3": _TranscodeTargetConfig(
        args=("-c:a", "libmp3lame", "-q:a", "2"),
        codec_name="libmp3lame",
        encoder_names=("libmp3lame", "mp3"),
    ),
    "ogg": _TranscodeTargetConfig(
        args=("-c:a", "libvorbis", "-q:a", "5"),
        codec_name="libvorbis",
        encoder_names=("libvorbis", "vorbis"),
    ),
    "opus": _TranscodeTargetConfig(
        args=("-c:a", "libopus", "-b:a", "192k", "-ar", "48000"),
        codec_name="libopus",
        encoder_names=("libopus", "opus"),
    ),
    "m4a": _TranscodeTargetConfig(
        args=("-c:a", "aac", "-b:a", "256k"),
        codec_name="aac",
        encoder_names=("aac",),
    ),
    # Raw ADTS AAC is externally convertible, but the current tag layer cannot write MP4 tags to it.
    "aac": _TranscodeTargetConfig(
        args=("-c:a", "aac", "-b:a", "256k"),
        codec_name="aac",
        encoder_names=("aac",),
    ),
}


@dataclass(frozen=True, slots=True)
class AudioConversionResult:
    destination_path: Path
    output_format: str
    codec_name: str | None


@dataclass(frozen=True, slots=True)
class AudioConversionCapabilities:
    ffmpeg_path: Path | None
    managed_targets: tuple[AudioFormatProfile, ...]
    managed_forensic_targets: tuple[AudioFormatProfile, ...]
    managed_lossy_targets: tuple[AudioFormatProfile, ...]
    external_targets: tuple[AudioFormatProfile, ...]


class AudioConversionService:
    """Feature-gated audio conversion service built on ffmpeg."""

    def __init__(self, *, ffmpeg_path: str | Path | None = None):
        resolved = Path(ffmpeg_path).expanduser() if ffmpeg_path else None
        self._ffmpeg_path = resolved or self._find_ffmpeg()
        self._encoders: set[str] | None = None
        self._managed_forensic_targets: tuple[AudioFormatProfile, ...] | None = None
        self._managed_lossy_targets: tuple[AudioFormatProfile, ...] | None = None

    @staticmethod
    def _find_ffmpeg() -> Path | None:
        executable = shutil.which("ffmpeg")
        return Path(executable) if executable else None

    def ffmpeg_path(self) -> Path | None:
        return self._ffmpeg_path

    def is_available(self) -> bool:
        return self._ffmpeg_path is not None and self._ffmpeg_path.exists()

    def require_available(self) -> Path:
        executable = self.ffmpeg_path()
        if executable is None or not executable.exists():
            raise RuntimeError(
                "Audio conversion requires ffmpeg on PATH. Install ffmpeg and try again."
            )
        return executable

    def _load_encoders(self) -> set[str]:
        if self._encoders is not None:
            return self._encoders
        if not self.is_available():
            self._encoders = set()
            return self._encoders
        try:
            completed = subprocess.run(
                [str(self.require_available()), "-hide_banner", "-encoders"],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            self._encoders = set()
            return self._encoders
        encoders: set[str] = set()
        for line in completed.stdout.splitlines():
            match = _ENCODER_LINE_PATTERN.match(line)
            if match:
                encoders.add(match.group(1).strip())
        self._encoders = encoders
        return encoders

    def _supports_encoder(self, *encoder_names: str) -> bool:
        encoders = self._load_encoders()
        return any(name in encoders for name in encoder_names)

    def _target_config(self, target_id: str) -> _TranscodeTargetConfig | None:
        clean_id = str(target_id or "").strip().lower()
        if not clean_id:
            return None
        return _TRANSCODE_TARGETS.get(clean_id)

    def _supports_target_profile(self, profile: AudioFormatProfile) -> bool:
        config = self._target_config(profile.id)
        if config is None:
            return False
        if not config.encoder_names:
            return True
        return self._supports_encoder(*config.encoder_names)

    @staticmethod
    def _write_probe_source(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = 4800
        silent_frame = b"\x00\x00\x00\x00"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(silent_frame * frame_count)

    def _managed_tagged_target_usable(self, profile: AudioFormatProfile) -> bool:
        if not self.is_available() or not self._supports_target_profile(profile):
            return False
        try:
            with tempfile.TemporaryDirectory(
                prefix=f"audio-conversion-{profile.id}-"
            ) as temp_dir_text:
                temp_dir = Path(temp_dir_text)
                source_path = temp_dir / "probe.wav"
                destination_path = temp_dir / f"probe{profile.suffixes[0]}"
                self._write_probe_source(source_path)
                self.transcode(
                    source_path=source_path,
                    destination_path=destination_path,
                    target_id=profile.id,
                )
                tag_service = AudioTagService()
                probe_tags = AudioTagData(title="Capability Probe", artist="ISRC Catalog Manager")
                tag_service.write_tags(destination_path, probe_tags)
                written_tags = tag_service.read_tags(destination_path)
                return written_tags.title == probe_tags.title
        except Exception:
            return False

    # Backwards-compatible seam retained for existing managed-lossy tests.
    def _managed_lossy_target_usable(self, profile: AudioFormatProfile) -> bool:
        return self._managed_tagged_target_usable(profile)

    def _managed_forensic_capabilities(self) -> tuple[AudioFormatProfile, ...]:
        if self._managed_forensic_targets is not None:
            return self._managed_forensic_targets
        if not self.is_available():
            self._managed_forensic_targets = tuple()
            return self._managed_forensic_targets
        supported: list[AudioFormatProfile] = []
        for profile in forensic_target_profiles():
            if self._managed_tagged_target_usable(profile):
                supported.append(profile)
        self._managed_forensic_targets = tuple(supported)
        return self._managed_forensic_targets

    def _managed_lossy_capabilities(self) -> tuple[AudioFormatProfile, ...]:
        if self._managed_lossy_targets is not None:
            return self._managed_lossy_targets
        if not self.is_available():
            self._managed_lossy_targets = tuple()
            return self._managed_lossy_targets
        supported: list[AudioFormatProfile] = []
        for profile in managed_lossy_target_profiles():
            if self._managed_lossy_target_usable(profile):
                supported.append(profile)
        self._managed_lossy_targets = tuple(supported)
        return self._managed_lossy_targets

    def capabilities(self) -> AudioConversionCapabilities:
        managed_targets = (
            tuple(
                profile
                for profile in managed_derivative_target_profiles()
                if self._supports_target_profile(profile)
            )
            if self.is_available()
            else tuple()
        )
        managed_forensic_targets = self._managed_forensic_capabilities()
        managed_lossy_targets = self._managed_lossy_capabilities()
        external_targets = (
            tuple(
                profile
                for profile in audio_format_profiles()
                if self._supports_target_profile(profile)
            )
            if self.is_available()
            else tuple()
        )
        return AudioConversionCapabilities(
            ffmpeg_path=self.ffmpeg_path(),
            managed_targets=managed_targets,
            managed_forensic_targets=managed_forensic_targets,
            managed_lossy_targets=managed_lossy_targets,
            external_targets=external_targets,
        )

    def managed_target_ids(self) -> tuple[str, ...]:
        return tuple(profile.id for profile in self.capabilities().managed_targets)

    def managed_authenticity_target_ids(self) -> tuple[str, ...]:
        return self.managed_target_ids()

    def managed_forensic_target_ids(self) -> tuple[str, ...]:
        return tuple(profile.id for profile in self.capabilities().managed_forensic_targets)

    def managed_lossy_target_ids(self) -> tuple[str, ...]:
        return tuple(profile.id for profile in self.capabilities().managed_lossy_targets)

    def managed_any_target_ids(self) -> tuple[str, ...]:
        ordered_ids: list[str] = []
        for format_id in self.managed_target_ids() + self.managed_lossy_target_ids():
            if format_id not in ordered_ids:
                ordered_ids.append(format_id)
        return tuple(ordered_ids)

    def external_target_ids(self) -> tuple[str, ...]:
        return tuple(profile.id for profile in self.capabilities().external_targets)

    def is_supported_target(
        self,
        format_id: str,
        *,
        managed_only: bool = False,
        capability_group: str | None = None,
    ) -> bool:
        clean_id = str(format_id or "").strip().lower()
        if capability_group == "managed_authenticity":
            supported = self.managed_authenticity_target_ids()
        elif capability_group == "managed_forensic":
            supported = self.managed_forensic_target_ids()
        elif capability_group == "managed_lossy":
            supported = self.managed_lossy_target_ids()
        elif capability_group in {"managed", "managed_any"}:
            supported = self.managed_any_target_ids()
        elif managed_only:
            supported = self.managed_target_ids()
        else:
            supported = self.external_target_ids()
        return clean_id in supported

    def _transcode_args(self, target_id: str) -> tuple[list[str], str | None]:
        config = self._target_config(target_id)
        if config is not None:
            return (list(config.args), config.codec_name)
        raise ValueError(f"Unsupported conversion target: {target_id}")

    def transcode(
        self,
        *,
        source_path: str | Path,
        destination_path: str | Path,
        target_id: str,
    ) -> AudioConversionResult:
        executable = self.require_available()
        source = Path(source_path)
        destination = Path(destination_path)
        if not source.exists():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        args, codec_name = self._transcode_args(target_id)
        command = [
            str(executable),
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            *args,
            str(destination),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        if not destination.exists():
            raise RuntimeError(f"ffmpeg did not create {destination}")
        return AudioConversionResult(
            destination_path=destination,
            output_format=str(target_id or "").strip().lower(),
            codec_name=codec_name,
        )

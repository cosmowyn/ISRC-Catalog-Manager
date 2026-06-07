from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.media import conversion
from isrc_manager.media.audio_formats import AudioFormatProfile
from isrc_manager.media.conversion import AudioConversionService


def _profile(format_id: str) -> AudioFormatProfile:
    return AudioFormatProfile(
        id=format_id,
        label=format_id.upper(),
        suffixes=(f".{format_id}",),
        mime_types=(f"audio/{format_id}",),
        lossy=format_id not in {"wav", "flac", "aiff"},
    )


def test_ffmpeg_candidate_paths_include_env_bundle_executable_and_platform_paths(
    monkeypatch,
    tmp_path,
):
    custom_ffmpeg = tmp_path / "custom" / "ffmpeg"
    bundle_root = tmp_path / "bundle"
    executable = tmp_path / "App" / "Python"
    monkeypatch.setenv("ISRC_MANAGER_FFMPEG", f" {custom_ffmpeg} ")
    monkeypatch.setenv("FFMPEG_BINARY", str(custom_ffmpeg))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    monkeypatch.setattr(conversion.platform, "system", lambda: "Darwin")
    darwin_paths = conversion._ffmpeg_candidate_paths()

    assert darwin_paths.count(custom_ffmpeg) == 1
    assert bundle_root / "ffmpeg" in darwin_paths
    assert bundle_root / "bin" / "ffmpeg" in darwin_paths
    assert executable.with_name("ffmpeg") in darwin_paths
    assert Path("/opt/homebrew/bin/ffmpeg") in darwin_paths

    monkeypatch.setattr(conversion.platform, "system", lambda: "Windows")
    windows_paths = conversion._ffmpeg_candidate_paths()
    assert any(str(path).lower().endswith("ffmpeg.exe") for path in windows_paths)

    monkeypatch.setattr(conversion.platform, "system", lambda: "Linux")
    linux_paths = conversion._ffmpeg_candidate_paths()
    assert Path("/usr/bin/ffmpeg") in linux_paths


def test_load_encoders_handles_unavailable_failures_success_and_cache(monkeypatch, tmp_path):
    unavailable = AudioConversionService(ffmpeg_path=tmp_path / "missing-ffmpeg")
    assert unavailable._load_encoders() == set()

    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    monkeypatch.setattr(
        conversion.subprocess,
        "run",
        mock.Mock(side_effect=RuntimeError("ffmpeg failed")),
    )
    assert service._load_encoders() == set()

    completed = SimpleNamespace(
        stdout="\n".join(
            [
                " A..... flac             FLAC",
                "not an encoder line",
                " A..... aac              AAC",
            ]
        )
    )
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    run_mock = mock.Mock(return_value=completed)
    monkeypatch.setattr(conversion.subprocess, "run", run_mock)

    assert service._load_encoders() == {"flac", "aac"}
    assert service._load_encoders() == {"flac", "aac"}
    run_mock.assert_called_once()


def test_target_support_and_capability_group_branches(tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    service._load_encoders = mock.Mock(return_value={"aac"})

    assert service._target_config("") is None
    assert service._supports_target_profile(_profile("unknown")) is False
    assert service._supports_target_profile(_profile("wav")) is True
    assert service._supports_target_profile(_profile("m4a")) is True
    assert service._supports_encoder("aac", "missing") is True
    assert service._supports_encoder("missing") is False

    wav = _profile("wav")
    mp3 = _profile("mp3")
    ogg = _profile("ogg")
    flac = _profile("flac")
    service.capabilities = mock.Mock(
        return_value=SimpleNamespace(
            managed_targets=(wav, mp3),
            managed_forensic_targets=(flac,),
            managed_lossy_targets=(mp3, ogg),
            external_targets=(wav, flac, ogg),
        )
    )

    assert service.managed_authenticity_target_ids() == ("wav", "mp3")
    assert service.managed_forensic_target_ids() == ("flac",)
    assert service.managed_lossy_target_ids() == ("mp3", "ogg")
    assert service.managed_any_target_ids() == ("wav", "mp3", "ogg")
    assert service.external_target_ids() == ("wav", "flac", "ogg")
    assert service.is_supported_target(" WAV ", capability_group="managed_authenticity") is True
    assert service.is_supported_target("flac", capability_group="managed_forensic") is True
    assert service.is_supported_target("ogg", capability_group="managed_lossy") is True
    assert service.is_supported_target("mp3", capability_group="managed_any") is True
    assert service.is_supported_target("wav", managed_only=True) is True
    assert service.is_supported_target("flac") is True
    assert service.is_supported_target("") is False


def test_managed_capability_caches_handle_unavailable_and_supported_profiles(monkeypatch, tmp_path):
    unavailable = AudioConversionService(ffmpeg_path=tmp_path / "missing-ffmpeg")
    assert unavailable._managed_forensic_capabilities() == tuple()
    assert unavailable._managed_forensic_capabilities() == tuple()
    assert unavailable._managed_lossy_capabilities() == tuple()
    assert unavailable._managed_lossy_capabilities() == tuple()

    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    monkeypatch.setattr(
        conversion, "forensic_target_profiles", lambda: (_profile("wav"), _profile("mp3"))
    )
    monkeypatch.setattr(
        conversion, "managed_lossy_target_profiles", lambda: (_profile("mp3"), _profile("ogg"))
    )
    service._managed_tagged_target_usable = mock.Mock(
        side_effect=lambda profile: profile.id in {"wav", "ogg"}
    )

    assert tuple(profile.id for profile in service._managed_forensic_capabilities()) == ("wav",)
    assert tuple(profile.id for profile in service._managed_forensic_capabilities()) == ("wav",)
    assert tuple(profile.id for profile in service._managed_lossy_capabilities()) == ("ogg",)
    assert tuple(profile.id for profile in service._managed_lossy_capabilities()) == ("ogg",)


def test_managed_tagged_target_probe_success_and_failures(monkeypatch, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    profile = _profile("wav")
    service._supports_target_profile = mock.Mock(return_value=True)
    service.transcode = mock.Mock()

    class FakeTagService:
        def write_tags(self, path, tags):
            Path(path).write_bytes(b"tagged")

        def read_tags(self, _path):
            return SimpleNamespace(title="Capability Probe")

    monkeypatch.setattr(conversion, "AudioTagService", FakeTagService)

    assert service._managed_tagged_target_usable(profile) is True

    service.transcode = mock.Mock(side_effect=RuntimeError("transcode failed"))
    assert service._managed_tagged_target_usable(profile) is False

    service.is_available = mock.Mock(return_value=False)
    assert service._managed_tagged_target_usable(profile) is False


def test_transcode_validation_success_and_output_failure(monkeypatch, tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    service = AudioConversionService(ffmpeg_path=fake_ffmpeg)
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF")

    with pytest.raises(FileNotFoundError):
        service.transcode(
            source_path=tmp_path / "missing.wav",
            destination_path=tmp_path / "out.wav",
            target_id="wav",
        )
    with pytest.raises(ValueError, match="Unsupported conversion target"):
        service.transcode(
            source_path=source,
            destination_path=tmp_path / "bad-target.out",
            target_id="bad",
        )
    with pytest.raises(ValueError, match="Unsupported metadata behavior"):
        service.transcode(
            source_path=source,
            destination_path=tmp_path / "bad-metadata.wav",
            target_id="wav",
            metadata_behavior="copy",
        )

    commands = []

    def fake_run(command, **kwargs):
        commands.append((list(command), kwargs))
        Path(command[-1]).write_bytes(b"converted")
        return SimpleNamespace()

    monkeypatch.setattr(conversion.subprocess, "run", fake_run)
    destination = tmp_path / "converted.wav"
    result = service.transcode(
        source_path=source,
        destination_path=destination,
        target_id="wav",
    )

    assert result.destination_path == destination
    assert result.output_format == "wav"
    assert result.codec_name == "pcm_s24le"
    assert commands[-1][0][-1] == str(destination)
    assert "-map_metadata" not in commands[-1][0]
    assert commands[-1][1]["check"] is True

    def fake_run_without_output(command, **kwargs):
        commands.append((list(command), kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(conversion.subprocess, "run", fake_run_without_output)
    with pytest.raises(RuntimeError, match="ffmpeg did not create"):
        service.transcode(
            source_path=source,
            destination_path=tmp_path / "missing-output.wav",
            target_id="wav",
        )

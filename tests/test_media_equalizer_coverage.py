from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from isrc_manager.media import equalizer


def test_normalize_equalizer_settings_handles_gains_string_and_defaults() -> None:
    normalized = equalizer.normalize_equalizer_settings(
        {
            "enabled": "yes",
            "gains": '[4.8, "bad", 0, -8]',
            "pan": "1.23",
        }
    )
    assert normalized["enabled"] is True
    assert normalized["pan"] == 1.0
    assert normalized["gains"][0] == 5.0
    assert normalized["gains"][1] == 0.0
    assert normalized["gains"][7] == 0.0


def test_normalize_equalizer_settings_non_dict_returns_default() -> None:
    normalized = equalizer.normalize_equalizer_settings(None)
    assert normalized["enabled"] is False
    assert normalized["pan"] == 0.0
    assert len(normalized["gains"]) == len(equalizer.EQUALIZER_BANDS)


def test_ffmpeg_filter_chain_no_active_gains() -> None:
    assert (
        equalizer._ffmpeg_filter_chain(
            {"enabled": True, "gains": [0.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0}
        )
        == ""
    )


def test_ffmpeg_filter_chain_active_gains() -> None:
    chain = equalizer._ffmpeg_filter_chain(
        {
            "enabled": True,
            "gains": [9.0, -6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "pan": 0.0,
        }
    )
    assert "bass=" in chain
    assert "treble=" in chain
    assert "equalizer=" in chain
    assert "volume=0.95" in chain
    assert "alimiter=limit=0.98" in chain


def test_which_prefers_shutil_which_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(equalizer.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert equalizer._which("ffmpeg") == "/usr/bin/ffmpeg"


def test_which_uses_platform_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(equalizer.shutil, "which", lambda name: None)
    monkeypatch.setattr(equalizer.platform, "system", lambda: "linux")
    monkeypatch.setattr(equalizer.os.path, "exists", lambda path: path == "/usr/local/bin/ffmpeg")
    assert equalizer._which("ffmpeg") == "/usr/local/bin/ffmpeg"


def test_apply_equalizer_to_audio_short_circuits_without_gain(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    source.write_bytes(b"dummy")

    assert not equalizer.apply_equalizer_to_audio(
        str(source),
        str(target),
        {"enabled": False, "gains": [0.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
    )
    assert not target.exists()


def test_apply_equalizer_to_audio_prefers_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    source.write_bytes(b"dummy")

    monkeypatch.setattr(equalizer, "_which", lambda name: "/usr/bin/ffmpeg")

    def fake_chain(value):
        return "volume=1"

    monkeypatch.setattr(equalizer, "_ffmpeg_filter_chain", fake_chain)

    def fake_run(cmd, *args, **kwargs):
        target.write_text("out")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(equalizer.subprocess, "run", fake_run)
    assert equalizer.apply_equalizer_to_audio(
        str(source),
        str(target),
        {
            "enabled": True,
            "gains": [1.0] + [0.0] * (len(equalizer.EQUALIZER_BANDS) - 1),
            "pan": 0.0,
        },
    )
    assert target.exists()
    assert target.stat().st_size > 0


def test_apply_equalizer_with_ffmpeg_false_when_no_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(equalizer, "_which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(equalizer, "_ffmpeg_filter_chain", lambda value: "")
    assert (
        equalizer._apply_equalizer_with_ffmpeg(
            "source.wav",
            "target.wav",
            {"enabled": True, "gains": [0.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
        )
        is False
    )


def test_equalizer_response_for_bins_empty_or_disabled() -> None:
    disabled = equalizer.equalizer_response_for_bins(
        0,
        {"enabled": True, "gains": [0.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
    )
    assert disabled == []

    muted = equalizer.equalizer_response_for_bins(
        4,
        {"enabled": False, "gains": [0.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
        frequency_scale="log",
    )
    assert muted == [1.0, 1.0, 1.0, 1.0]


def test_biquad_coefficients_cover_filter_variants() -> None:
    low_shelf = equalizer.equalizer_biquad_coefficients("low_shelf", 100.0, 0.8, 1.5, 44100)
    high_shelf = equalizer.equalizer_biquad_coefficients("high_shelf", 20000.0, 0.7, -1.0, 48000)
    bell = equalizer.equalizer_biquad_coefficients("bell", 800.0, 0.9, 0.0, 22050)

    assert all(not np.isnan(value) for value in low_shelf)
    assert all(not np.isnan(value) for value in high_shelf)
    assert all(not np.isnan(value) for value in bell)
    assert low_shelf != high_shelf
    assert low_shelf != bell


def test_response_db_enables_filter_contributions() -> None:
    value = equalizer.equalizer_response_db_at_frequency(
        1000.0,
        {
            "enabled": True,
            "gains": [1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "pan": 0.0,
        },
    )
    assert value != 0.0

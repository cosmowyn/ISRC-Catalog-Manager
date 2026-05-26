from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

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


def test_load_and_save_equalizer_settings_handle_typed_fallbacks_and_failures() -> None:
    class FallbackSettings:
        def __init__(self) -> None:
            self.saved: dict[str, object] = {}
            self.synced = False

        def value(self, key, default=None, value_type=None):
            if value_type is not None:
                raise TypeError("typed values unsupported")
            return {
                equalizer.EQ_SETTINGS_ENABLED_KEY: "on",
                equalizer.EQ_SETTINGS_GAINS_KEY: "[1, 2, 3]",
                equalizer.EQ_SETTINGS_PAN_KEY: "-0.25",
            }.get(key, default)

        def setValue(self, key, value):
            self.saved[key] = value

        def sync(self):
            self.synced = True

    settings = FallbackSettings()
    loaded = equalizer.load_equalizer_settings(settings)
    assert loaded["enabled"] is True
    assert loaded["gains"][:3] == [1.0, 2.0, 3.0]
    assert loaded["pan"] == -0.25

    saved = equalizer.save_equalizer_settings(
        settings,
        {"enabled": True, "gains": [12.0, "bad"], "pan": "bad"},
    )
    assert saved["gains"][0] == equalizer.EQ_GAIN_MAX_DB
    assert saved["gains"][1] == 0.0
    assert settings.saved[equalizer.EQ_SETTINGS_ENABLED_KEY] is True
    assert settings.synced is True

    class BrokenSettings:
        def value(self, *_args, **_kwargs):
            raise RuntimeError("cannot read")

        def setValue(self, *_args, **_kwargs):
            raise RuntimeError("cannot write")

    assert (
        equalizer.load_equalizer_settings(BrokenSettings())
        == equalizer.default_equalizer_settings()
    )
    assert equalizer.save_equalizer_settings(BrokenSettings(), {"enabled": True})["enabled"] is True


def test_equalizer_response_helpers_cover_disabled_log_linear_and_audible_gain() -> None:
    assert equalizer.equalizer_is_enabled({"enabled": "true"}) is True
    assert equalizer.equalizer_has_audible_gain({"enabled": True, "gains": [0.01]}) is False
    assert equalizer.equalizer_has_audible_gain({"enabled": True, "gains": [0.5]}) is True
    assert equalizer.equalizer_response_db_at_frequency(1000, {"enabled": False}) == 0.0

    linear = equalizer.equalizer_response_for_bins(
        3,
        {"enabled": True, "gains": [1.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
        frequency_scale="linear",
        min_hz=20,
        max_hz=20000,
    )
    log = equalizer.equalizer_response_for_bins(
        3,
        {"enabled": True, "gains": [1.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0},
        frequency_scale="log",
        min_hz=20,
        max_hz=20000,
    )
    assert len(linear) == 3
    assert len(log) == 3
    assert linear != log


def test_ffmpeg_and_soundfile_paths_report_missing_tools_and_runtime_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(equalizer.shutil, "which", lambda _name: None)
    monkeypatch.setattr(equalizer.platform, "system", lambda: "windows")
    monkeypatch.setattr(
        equalizer.os.path,
        "exists",
        lambda path: path.endswith("ffmpeg.exe"),
    )
    assert equalizer._which("ffmpeg") is not None

    monkeypatch.setattr(equalizer, "_which", lambda _name: None)
    assert (
        equalizer._apply_equalizer_with_ffmpeg("source.wav", "target.wav", {"enabled": True})
        is False
    )

    monkeypatch.setattr(equalizer, "_which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(equalizer, "_ffmpeg_filter_chain", lambda _value: "volume=1")
    monkeypatch.setattr(
        equalizer.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ffmpeg failed")),
    )
    assert (
        equalizer._apply_equalizer_with_ffmpeg("source.wav", "target.wav", {"enabled": True})
        is False
    )

    source = tmp_path / "not-a-real.wav"
    target = tmp_path / "target.wav"
    source.write_bytes(b"not audio")
    assert (
        equalizer._apply_equalizer_with_soundfile(str(source), str(target), {"enabled": True})
        is False
    )


def test_curve_widget_audio_spectrum_and_geometry_helpers() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    widget = equalizer.EqualizerCurveWidget()
    try:
        widget.set_settings(
            {"enabled": True, "gains": [2.0] * len(equalizer.EQUALIZER_BANDS), "pan": 0.0}
        )
        widget.set_audio_spectrum([0.2, 0.8, 2.0])
        assert widget._audio_spectrum_values == [0.2, 0.8, 1.24]
        widget.set_audio_spectrum([0.8, 0.4, 1.0])
        assert len(widget._audio_spectrum_values) == 3
        assert widget._audio_spectrum_opacity > 0.0

        rect = widget.rect().adjusted(0, 0, 120, 80)
        x_low = widget._frequency_to_x(20, rect)
        x_high = widget._frequency_to_x(20000, rect)
        assert x_low < x_high
        assert widget._db_to_y(equalizer.EQ_GAIN_MIN_DB, rect) > widget._db_to_y(
            equalizer.EQ_GAIN_MAX_DB,
            rect,
        )
        assert widget._relative_luminance(QColor("#ffffff")) > widget._relative_luminance(
            QColor("#000000")
        )
        color = widget._audio_spectrum_color(0.8, light_mode=True)
        assert color.isValid()

        widget._last_audio_spectrum_update = equalizer.monotonic()
        before_opacity = widget._audio_spectrum_opacity
        widget._advance_audio_spectrum_fade()
        assert widget._audio_spectrum_opacity == before_opacity

        widget._last_audio_spectrum_update = 0.0
        widget._audio_spectrum_opacity = 0.01
        widget._audio_spectrum_values = [0.1, 0.2]
        widget._advance_audio_spectrum_fade()
        assert widget._audio_spectrum_opacity == 0.0
        assert widget._audio_spectrum_values == []
    finally:
        widget.deleteLater()


def test_panning_dial_widget_coerces_pan_and_falls_back_to_legacy_event_positions() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    widget = equalizer.PanningDialWidget()
    emissions: list[float] = []
    widget.panChanged.connect(emissions.append)
    try:
        widget.set_pan("0.004", emit=True)
        assert widget.pan() == 0.0
        assert emissions == []

        widget.set_pan("1.5", emit=True)
        assert widget.pan() == 1.0
        assert emissions == [1.0]
        widget.set_pan(-0.33)
        assert widget.pan() == -0.33

        center, radius = widget._arc_geometry()
        left = equalizer.PanningDialWidget._point_from_pan(center, radius, -1.0)
        right = equalizer.PanningDialWidget._point_from_pan(center, radius, 1.0)
        assert left.x() < right.x()

        class LegacyEvent:
            def position(self):
                raise AttributeError

            def pos(self):
                return QPoint(10, 20)

        assert widget._event_position(LegacyEvent()) == QPointF(10, 20)
        assert widget._pan_from_position(QPointF(center.x(), center.y())) == 0.0
        assert widget._relative_luminance(QColor("#ffffff")) > widget._relative_luminance(
            QColor("#000000")
        )
    finally:
        widget.deleteLater()

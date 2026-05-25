from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from isrc_manager.forensics.watermark import (
    ForensicWatermarkCore,
    ForensicWatermarkExtractionResult,
    ForensicWatermarkToken,
    forensic_watermark_settings_payload,
    pack_token,
    supported_forensic_audio_path,
    sync_and_payload_bits,
    unpack_token,
)


def test_forensic_pack_unpack_round_trip() -> None:
    token = ForensicWatermarkToken(version=1, token_id=77, binding_crc32=0x89ABCDEF)
    packed = pack_token(token)
    unpacked = unpack_token(packed)

    assert len(packed) == 15
    assert token.crc32 is not None
    assert unpacked.version == token.version
    assert unpacked.token_id == token.token_id
    assert unpacked.binding_crc32 == token.binding_crc32
    assert unpacked.crc32 == token.crc32


def test_forensic_pack_token_rejects_out_of_range_id() -> None:
    with pytest.raises(ValueError, match="must fit in 48 bits"):
        pack_token(ForensicWatermarkToken(version=1, token_id=(1 << 48), binding_crc32=0))


def test_supported_forensic_audio_path_recognizes_known_formats() -> None:
    assert supported_forensic_audio_path("track.wav")
    assert supported_forensic_audio_path("TRACK.FLAC")
    assert not supported_forensic_audio_path("notes.txt")


def test_forensic_watermark_settings_payload_shape() -> None:
    payload = forensic_watermark_settings_payload()

    assert payload["token_bytes"] == 15
    assert payload["frame_length"] > 0
    assert payload["hop_length"] > 0
    assert payload["sync_word_hex"] == "96b3"


def test_extract_from_path_no_keys_is_insufficient() -> None:
    core = ForensicWatermarkCore()
    result = core.extract_from_path("unused/path.wav", watermark_keys=[])

    assert isinstance(result, ForensicWatermarkExtractionResult)
    assert result.status == "insufficient"
    assert result.key_id is None
    assert result.token is None


def test_extract_from_path_handles_non_audio_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "dummy.wav"
    source.write_bytes(b"not audio")

    import isrc_manager.forensics.watermark as wm

    def fake_read_audio(*_args, **_kwargs):
        return (np.zeros((0, 2), dtype=np.float32), 44100, "wav", "")

    monkeypatch.setattr(wm, "_read_audio", fake_read_audio)
    core = wm.ForensicWatermarkCore()
    result = core.extract_from_path(str(source), watermark_keys=[("primary", b"k")])

    assert result.status == "none"
    assert result.token is None
    assert result.repeat_groups == 0


def test_verify_expected_token_reference_samplerate_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import isrc_manager.forensics.watermark as wm

    token = ForensicWatermarkToken(version=1, token_id=22, binding_crc32=123456)

    def fake_read_audio(*_args, **_kwargs):
        source_path = _kwargs.get("source_path")
        if source_path is None and _args:
            source_path = _args[0]
        if source_path == "candidate.wav":
            return (np.ones((1024, 2), dtype=np.float32), 44100, "wav", "")
        return (np.ones((1024, 2), dtype=np.float32), 48000, "wav", "")

    monkeypatch.setattr(wm, "_read_audio", fake_read_audio)
    core = wm.ForensicWatermarkCore()
    result = core.verify_expected_token_against_reference(
        "candidate.wav",
        reference_path="reference.wav",
        watermark_keys=[("primary", b"abc")],
        token=token,
    )

    assert result.status == "insufficient"
    assert result.token == token
    assert not result.crc_ok


def test_verify_expected_token_reference_can_skip_empty_measurement_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import isrc_manager.forensics.watermark as wm

    token = ForensicWatermarkToken(version=1, token_id=7, binding_crc32=42)
    expected_bits = sync_and_payload_bits(token)

    def fake_read_audio(*_args, **_kwargs):
        return (np.ones((1024, 2), dtype=np.float32), 44100, "wav", "")

    def fake_stft_channel(*_args, **_kwargs):
        frequencies = np.array([40.0, 80.0, 160.0, 400.0], dtype=np.float64)
        return frequencies, np.zeros((4, 500), dtype=np.complex64)

    def fake_eligible_bins(_frequencies: np.ndarray) -> np.ndarray:
        return np.array([0, 1], dtype=np.int64)

    def fake_reference_difference_matrix(*_args, **kwargs) -> np.ndarray:
        repeat_groups = int(kwargs.get("repeat_groups", 1))
        bit_count = int(kwargs.get("bit_count", expected_bits.size))
        return np.zeros((repeat_groups, bit_count), dtype=np.float32)

    monkeypatch.setattr(wm, "_read_audio", fake_read_audio)
    monkeypatch.setattr(wm, "_stft_channel", fake_stft_channel)
    monkeypatch.setattr(wm, "_eligible_bins", fake_eligible_bins)
    monkeypatch.setattr(
        wm.ForensicWatermarkCore,
        "_reference_difference_matrix",
        fake_reference_difference_matrix,
    )

    core = wm.ForensicWatermarkCore()
    result = core.verify_expected_token_against_reference(
        "candidate.wav",
        reference_path="reference.wav",
        watermark_keys=[("primary", b"abc")],
        token=token,
    )

    assert result.status == "none"
    assert result.token == token
    assert result.repeat_groups > 0
    assert result.mean_confidence == 0.0
    assert result.sync_score == 0.0
    assert not result.crc_ok

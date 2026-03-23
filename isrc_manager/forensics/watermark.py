"""Recipient-specific forensic watermark helpers for managed export copies."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from isrc_manager.authenticity.watermark import (
    EMBED_BINS_PER_BIT,
    EMBED_DELTA_CLIP,
    EMBED_STRENGTH,
    FRAME_LENGTH,
    FRAME_PATTERN,
    FRAMES_PER_BIT,
    GROUP_AGREEMENT_THRESHOLD,
    HOP_LENGTH,
    INSUFFICIENT_CONFIDENCE_THRESHOLD,
    MAX_REPEAT_GROUPS,
    MEAN_CONFIDENCE_THRESHOLD,
    MID_FREQ_MAX_HZ,
    MID_FREQ_MIN_HZ,
    REFERENCE_INSUFFICIENT_MEAN_SCORE,
    REFERENCE_INSUFFICIENT_POSITIVE_RATIO,
    REFERENCE_MEAN_SCORE_THRESHOLD,
    REFERENCE_POSITIVE_RATIO_THRESHOLD,
    REFERENCE_STRONG_RATIO_THRESHOLD,
    REFERENCE_STRONG_SCORE_FLOOR,
    REFERENCE_SYNC_RATIO_THRESHOLD,
    SYNC_SCORE_THRESHOLD,
    _correlation_score,
    _eligible_bins,
    _frame_schedule,
    _istft_channel,
    _read_audio,
    _stft_channel,
    _usable_frames,
    _write_audio,
)

from .models import ForensicWatermarkExtractionResult, ForensicWatermarkToken

FORENSIC_SYNC_WORD = 0x96B3
SUPPORTED_FORENSIC_SUFFIXES = frozenset({".wav", ".flac", ".aif", ".aiff"})


def supported_forensic_audio_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_FORENSIC_SUFFIXES


def pack_token(token: ForensicWatermarkToken) -> bytes:
    token_id = int(token.token_id)
    if token_id <= 0 or token_id >= (1 << 48):
        raise ValueError("Forensic token id must fit in 48 bits.")
    body = (
        bytes([int(token.version) & 0xFF])
        + token_id.to_bytes(6, "big", signed=False)
        + struct.pack(">I", int(token.binding_crc32) & 0xFFFFFFFF)
    )
    crc32_value = zlib.crc32(body) & 0xFFFFFFFF
    token.crc32 = crc32_value
    return body + struct.pack(">I", crc32_value)


def unpack_token(raw: bytes) -> ForensicWatermarkToken:
    if len(raw) != 15:
        raise ValueError("Forensic watermark token must be exactly 15 bytes.")
    version = int(raw[0])
    token_id = int.from_bytes(raw[1:7], "big", signed=False)
    binding_crc32 = struct.unpack(">I", raw[7:11])[0]
    crc32_value = struct.unpack(">I", raw[11:15])[0]
    return ForensicWatermarkToken(
        version=version,
        token_id=token_id,
        binding_crc32=int(binding_crc32),
        crc32=int(crc32_value),
    )


def sync_and_payload_bits(token: ForensicWatermarkToken) -> np.ndarray:
    sync_bits = np.asarray(
        [(FORENSIC_SYNC_WORD >> shift) & 1 for shift in range(15, -1, -1)],
        dtype=np.uint8,
    )
    payload = pack_token(token)
    payload_bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))
    return np.concatenate([sync_bits, payload_bits])


def forensic_watermark_settings_payload() -> dict[str, object]:
    return {
        "frame_length": FRAME_LENGTH,
        "hop_length": HOP_LENGTH,
        "bins_per_bit": EMBED_BINS_PER_BIT,
        "frames_per_bit": FRAMES_PER_BIT,
        "embed_strength": EMBED_STRENGTH,
        "embed_delta_clip": EMBED_DELTA_CLIP,
        "mid_freq_hz": [MID_FREQ_MIN_HZ, MID_FREQ_MAX_HZ],
        "sync_word_hex": f"{FORENSIC_SYNC_WORD:04x}",
        "token_bytes": 15,
    }


class ForensicWatermarkCore:
    """Implements recipient-specific watermark embed and detect operations."""

    def embed_to_path(
        self,
        *,
        source_path: str | Path | None = None,
        source_bytes: bytes | None = None,
        destination_path: str | Path,
        watermark_key: bytes,
        token: ForensicWatermarkToken,
    ) -> dict[str, float | int]:
        audio, sample_rate, _format_name, source_subtype = _read_audio(
            source_path=source_path,
            source_bytes=source_bytes,
        )
        if audio.ndim != 2 or audio.shape[0] <= 0:
            raise ValueError("Audio input could not be decoded into frame/channel data.")
        original = audio.copy()
        channel_stfts: list[np.ndarray] = []
        frequencies = None
        for channel_index in range(audio.shape[1]):
            channel_frequencies, stft_matrix = _stft_channel(audio[:, channel_index], sample_rate)
            if frequencies is None:
                frequencies = channel_frequencies
            channel_stfts.append(stft_matrix)
        if frequencies is None:
            raise ValueError("Could not determine STFT frequency bins.")
        mono = audio.mean(axis=1)
        _, mono_stft = _stft_channel(mono, sample_rate)
        eligible_bins = _eligible_bins(frequencies)
        usable_frames = _usable_frames(mono_stft, eligible_bins)
        all_bits = sync_and_payload_bits(token)
        frames_per_payload = int(all_bits.size) * FRAMES_PER_BIT
        repeat_groups = int(usable_frames.size // max(1, frames_per_payload))
        repeat_groups = min(repeat_groups, MAX_REPEAT_GROUPS)
        if repeat_groups <= 0:
            raise ValueError(
                "Audio is too short or too sparse for the configured forensic watermark payload."
            )

        for repeat_index in range(repeat_groups):
            for bit_index, bit_value in enumerate(all_bits.tolist()):
                selected_bins, chips = _frame_schedule(
                    watermark_key,
                    eligible_bins,
                    repeat_index,
                    bit_index,
                )
                symbol = 1.0 if int(bit_value) else -1.0
                frame_base = (repeat_index * frames_per_payload) + (bit_index * FRAMES_PER_BIT)
                for local_frame_offset in range(FRAMES_PER_BIT):
                    frame_index = int(usable_frames[frame_base + local_frame_offset])
                    frame_symbol = symbol * float(FRAME_PATTERN[local_frame_offset])
                    for stft_matrix in channel_stfts:
                        bins = stft_matrix[selected_bins, frame_index]
                        magnitudes = np.abs(bins).astype(np.float32, copy=False)
                        phases = np.angle(bins)
                        deltas = np.minimum(magnitudes * EMBED_STRENGTH, EMBED_DELTA_CLIP)
                        adjusted = np.maximum(
                            magnitudes + (frame_symbol * chips * deltas),
                            1.0e-7,
                        )
                        stft_matrix[selected_bins, frame_index] = adjusted * np.exp(1j * phases)

        rebuilt_channels = [
            _istft_channel(stft_matrix, sample_rate, audio.shape[0])
            for stft_matrix in channel_stfts
        ]
        rebuilt_audio = np.stack(rebuilt_channels, axis=1)
        rebuilt_audio = np.clip(rebuilt_audio, -1.0, 1.0).astype(np.float32, copy=False)
        _write_audio(destination_path, rebuilt_audio, sample_rate, source_subtype=source_subtype)
        delta = rebuilt_audio - original
        return {
            "sample_rate": int(sample_rate),
            "channels": int(rebuilt_audio.shape[1]),
            "frames": int(rebuilt_audio.shape[0]),
            "repeat_groups": int(repeat_groups),
            "rms_delta": float(np.sqrt(np.mean(np.square(delta), dtype=np.float64))),
            "peak_delta": float(np.max(np.abs(delta))),
        }

    def _measurement_matrix(
        self,
        *,
        mono_stft: np.ndarray,
        eligible_bins: np.ndarray,
        usable_frames: np.ndarray,
        watermark_key: bytes,
        bit_count: int,
        frames_per_payload: int,
        repeat_groups: int,
    ) -> np.ndarray:
        measurements = np.zeros((repeat_groups, bit_count), dtype=np.float32)
        for repeat_index in range(repeat_groups):
            for bit_index in range(bit_count):
                selected_bins, chips = _frame_schedule(
                    watermark_key,
                    eligible_bins,
                    repeat_index,
                    bit_index,
                )
                frame_base = (repeat_index * frames_per_payload) + (bit_index * FRAMES_PER_BIT)
                frame_scores: list[float] = []
                for local_frame_offset in range(FRAMES_PER_BIT):
                    frame_index = int(usable_frames[frame_base + local_frame_offset])
                    magnitudes = np.abs(mono_stft[selected_bins, frame_index]).astype(np.float32)
                    frame_score = _correlation_score(magnitudes, chips)
                    frame_scores.append(frame_score * float(FRAME_PATTERN[local_frame_offset]))
                measurements[repeat_index, bit_index] = float(np.mean(frame_scores))
        return measurements

    def extract_from_path(
        self,
        path: str | Path,
        *,
        watermark_keys: list[tuple[str, bytes]],
    ) -> ForensicWatermarkExtractionResult:
        if not watermark_keys:
            return ForensicWatermarkExtractionResult(
                status="insufficient",
                key_id=None,
                token=None,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )
        audio, sample_rate, _format_name, _subtype = _read_audio(source_path=path)
        if audio.ndim != 2 or audio.shape[0] <= 0:
            return ForensicWatermarkExtractionResult(
                status="none",
                key_id=None,
                token=None,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )
        mono = audio.mean(axis=1)
        frequencies, mono_stft = _stft_channel(mono, sample_rate)
        eligible_bins = _eligible_bins(frequencies)
        usable_frames = _usable_frames(mono_stft, eligible_bins)
        bit_count = 16 + (15 * 8)
        frames_per_payload = bit_count * FRAMES_PER_BIT
        repeat_groups = int(usable_frames.size // max(1, frames_per_payload))
        repeat_groups = min(repeat_groups, MAX_REPEAT_GROUPS)
        if repeat_groups <= 0:
            return ForensicWatermarkExtractionResult(
                status="none",
                key_id=None,
                token=None,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )

        best_result: ForensicWatermarkExtractionResult | None = None
        sync_bits = np.asarray(
            [(FORENSIC_SYNC_WORD >> shift) & 1 for shift in range(15, -1, -1)],
            dtype=np.uint8,
        )
        for key_id, watermark_key in watermark_keys:
            measurements = self._measurement_matrix(
                mono_stft=mono_stft,
                eligible_bins=eligible_bins,
                usable_frames=usable_frames,
                watermark_key=watermark_key,
                bit_count=bit_count,
                frames_per_payload=frames_per_payload,
                repeat_groups=repeat_groups,
            )
            majority_bits: list[int] = []
            confidence_values: list[float] = []
            matching_votes = 0
            total_votes = int(measurements.shape[0] * measurements.shape[1])
            for bit_index in range(bit_count):
                bit_scores = measurements[:, bit_index]
                positives = int(np.count_nonzero(bit_scores >= 0.0))
                negatives = int(bit_scores.size - positives)
                majority_is_one = positives >= negatives
                majority_bits.append(1 if majority_is_one else 0)
                majority_count = max(positives, negatives)
                matching_votes += majority_count
                confidence_values.append(float(majority_count / max(1, bit_scores.size)))

            sync_matches = sum(
                1
                for expected, actual in zip(sync_bits.tolist(), majority_bits[:16])
                if int(expected) == int(actual)
            )
            sync_score = float(sync_matches / 16.0)
            mean_confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
            group_agreement = float(matching_votes / max(1, total_votes))
            payload_bits = np.asarray(majority_bits[16:], dtype=np.uint8)
            payload_bytes = np.packbits(payload_bits).tobytes()
            crc_ok = False
            token = None
            if len(payload_bytes) == 15:
                expected_crc = zlib.crc32(payload_bytes[:11]) & 0xFFFFFFFF
                actual_crc = struct.unpack(">I", payload_bytes[11:15])[0]
                crc_ok = expected_crc == actual_crc
                if crc_ok:
                    token = unpack_token(payload_bytes)
            if (
                token is not None
                and crc_ok
                and sync_score >= SYNC_SCORE_THRESHOLD
                and mean_confidence >= MEAN_CONFIDENCE_THRESHOLD
                and group_agreement >= GROUP_AGREEMENT_THRESHOLD
            ):
                return ForensicWatermarkExtractionResult(
                    status="detected",
                    key_id=key_id,
                    token=token,
                    mean_confidence=mean_confidence,
                    sync_score=sync_score,
                    group_agreement=group_agreement,
                    repeat_groups=repeat_groups,
                    crc_ok=True,
                )

            status = (
                "insufficient"
                if max(sync_score, mean_confidence) >= INSUFFICIENT_CONFIDENCE_THRESHOLD
                else "none"
            )
            candidate = ForensicWatermarkExtractionResult(
                status=status,
                key_id=key_id,
                token=token,
                mean_confidence=mean_confidence,
                sync_score=sync_score,
                group_agreement=group_agreement,
                repeat_groups=repeat_groups,
                crc_ok=crc_ok,
            )
            if best_result is None or (
                candidate.mean_confidence,
                candidate.sync_score,
                candidate.group_agreement,
            ) > (
                best_result.mean_confidence,
                best_result.sync_score,
                best_result.group_agreement,
            ):
                best_result = candidate
        return best_result or ForensicWatermarkExtractionResult(
            status="none",
            key_id=None,
            token=None,
            mean_confidence=0.0,
            sync_score=0.0,
            group_agreement=0.0,
            repeat_groups=0,
            crc_ok=False,
        )

    def _reference_difference_matrix(
        self,
        *,
        candidate_stft: np.ndarray,
        reference_stft: np.ndarray,
        eligible_bins: np.ndarray,
        usable_frames: np.ndarray,
        watermark_key: bytes,
        bit_count: int,
        frames_per_payload: int,
        repeat_groups: int,
    ) -> np.ndarray:
        measurements = np.zeros((repeat_groups, bit_count), dtype=np.float32)
        for repeat_index in range(repeat_groups):
            for bit_index in range(bit_count):
                selected_bins, chips = _frame_schedule(
                    watermark_key,
                    eligible_bins,
                    repeat_index,
                    bit_index,
                )
                frame_base = (repeat_index * frames_per_payload) + (bit_index * FRAMES_PER_BIT)
                frame_scores: list[float] = []
                for local_frame_offset in range(FRAMES_PER_BIT):
                    frame_index = int(usable_frames[frame_base + local_frame_offset])
                    candidate_magnitudes = np.abs(
                        candidate_stft[selected_bins, frame_index]
                    ).astype(np.float32)
                    reference_magnitudes = np.abs(
                        reference_stft[selected_bins, frame_index]
                    ).astype(np.float32)
                    log_difference = np.log(np.maximum(candidate_magnitudes, 1.0e-7)) - np.log(
                        np.maximum(reference_magnitudes, 1.0e-7)
                    )
                    score = float(np.dot(log_difference, chips) / max(1, chips.size))
                    frame_scores.append(score * float(FRAME_PATTERN[local_frame_offset]))
                measurements[repeat_index, bit_index] = float(np.mean(frame_scores))
        return measurements

    def verify_expected_token_against_reference(
        self,
        candidate_path: str | Path,
        *,
        reference_path: str | Path | None = None,
        reference_bytes: bytes | None = None,
        watermark_keys: list[tuple[str, bytes]],
        token: ForensicWatermarkToken,
    ) -> ForensicWatermarkExtractionResult:
        if not watermark_keys:
            return ForensicWatermarkExtractionResult(
                status="insufficient",
                key_id=None,
                token=None,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )
        candidate_audio, candidate_sample_rate, _format_name, _subtype = _read_audio(
            source_path=candidate_path
        )
        reference_audio, reference_sample_rate, _reference_format, _reference_subtype = _read_audio(
            source_path=reference_path,
            source_bytes=reference_bytes,
        )
        if candidate_sample_rate != reference_sample_rate:
            return ForensicWatermarkExtractionResult(
                status="insufficient",
                key_id=None,
                token=token,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )
        candidate_mono = candidate_audio.mean(axis=1)
        reference_mono = reference_audio.mean(axis=1)
        frequencies, candidate_stft = _stft_channel(candidate_mono, candidate_sample_rate)
        _, reference_stft = _stft_channel(reference_mono, reference_sample_rate)
        eligible_bins = _eligible_bins(frequencies)
        bit_count = int(sync_and_payload_bits(token).size)
        frames_per_payload = bit_count * FRAMES_PER_BIT
        usable_frames = np.arange(
            min(candidate_stft.shape[1], reference_stft.shape[1]),
            dtype=np.int32,
        )
        repeat_groups = min(
            int(usable_frames.size // max(1, frames_per_payload)),
            MAX_REPEAT_GROUPS,
        )
        if repeat_groups <= 0:
            return ForensicWatermarkExtractionResult(
                status="none",
                key_id=None,
                token=token,
                mean_confidence=0.0,
                sync_score=0.0,
                group_agreement=0.0,
                repeat_groups=0,
                crc_ok=False,
            )

        expected_bits = sync_and_payload_bits(token)
        expected_signs = np.where(expected_bits > 0, 1.0, -1.0).astype(np.float32)
        best_result: ForensicWatermarkExtractionResult | None = None
        for key_id, watermark_key in watermark_keys:
            measurements = self._reference_difference_matrix(
                candidate_stft=candidate_stft,
                reference_stft=reference_stft,
                eligible_bins=eligible_bins,
                usable_frames=usable_frames,
                watermark_key=watermark_key,
                bit_count=bit_count,
                frames_per_payload=frames_per_payload,
                repeat_groups=repeat_groups,
            )
            signed_scores = measurements * expected_signs.reshape(1, -1)
            flattened = signed_scores.reshape(-1)
            if flattened.size <= 0:
                continue
            sync_values = signed_scores[:, :16].reshape(-1)
            mean_score = float(np.mean(flattened))
            positive_ratio = float(np.mean(flattened > 0.0))
            strong_ratio = float(np.mean(flattened > REFERENCE_STRONG_SCORE_FLOOR))
            sync_ratio = float(np.mean(sync_values > 0.0)) if sync_values.size > 0 else 0.0
            status = "none"
            if (
                mean_score >= REFERENCE_MEAN_SCORE_THRESHOLD
                and positive_ratio >= REFERENCE_POSITIVE_RATIO_THRESHOLD
                and strong_ratio >= REFERENCE_STRONG_RATIO_THRESHOLD
                and sync_ratio >= REFERENCE_SYNC_RATIO_THRESHOLD
            ):
                status = "detected"
            elif (
                mean_score >= REFERENCE_INSUFFICIENT_MEAN_SCORE
                or positive_ratio >= REFERENCE_INSUFFICIENT_POSITIVE_RATIO
            ):
                status = "insufficient"
            candidate = ForensicWatermarkExtractionResult(
                status=status,
                key_id=key_id,
                token=token,
                mean_confidence=positive_ratio,
                sync_score=sync_ratio,
                group_agreement=strong_ratio,
                repeat_groups=repeat_groups,
                crc_ok=(status == "detected"),
            )
            if candidate.status == "detected":
                return candidate
            if best_result is None or (
                candidate.mean_confidence,
                candidate.group_agreement,
                candidate.sync_score,
            ) > (
                best_result.mean_confidence,
                best_result.group_agreement,
                best_result.sync_score,
            ):
                best_result = candidate
        return best_result or ForensicWatermarkExtractionResult(
            status="none",
            key_id=None,
            token=token,
            mean_confidence=0.0,
            sync_score=0.0,
            group_agreement=0.0,
            repeat_groups=0,
            crc_ok=False,
        )

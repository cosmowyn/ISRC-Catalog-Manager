"""Deterministic manifest and fingerprint helpers."""

from __future__ import annotations

import base64
import json

import numpy as np
from scipy import signal

from .crypto import canonical_json_bytes

FINGERPRINT_SAMPLE_RATE = 8000
FINGERPRINT_FRAME_LENGTH = 2048
FINGERPRINT_HOP_LENGTH = 512
FINGERPRINT_BAND_COUNT = 24
FINGERPRINT_DELTA_BINS = 16


def manifest_bytes(payload: dict[str, object]) -> bytes:
    return canonical_json_bytes(payload)


def manifest_text(payload: dict[str, object]) -> str:
    return manifest_bytes(payload).decode("utf-8")


def canonical_text(data: dict[str, object]) -> str:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _resample_mono(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sample_rate == FINGERPRINT_SAMPLE_RATE:
        return data.astype(np.float32, copy=False)
    gcd = np.gcd(sample_rate, FINGERPRINT_SAMPLE_RATE)
    up = FINGERPRINT_SAMPLE_RATE // gcd
    down = sample_rate // gcd
    return signal.resample_poly(data, up, down).astype(np.float32, copy=False)


def compute_reference_fingerprint(audio: np.ndarray, sample_rate: int) -> str:
    mono = _resample_mono(audio, sample_rate)
    if mono.size == 0:
        mono = np.zeros(FINGERPRINT_FRAME_LENGTH, dtype=np.float32)
    if mono.size < FINGERPRINT_FRAME_LENGTH:
        mono = np.pad(mono, (0, FINGERPRINT_FRAME_LENGTH - mono.size))
    frequencies, _, stft_matrix = signal.stft(
        mono,
        fs=FINGERPRINT_SAMPLE_RATE,
        window="hann",
        nperseg=FINGERPRINT_FRAME_LENGTH,
        noverlap=FINGERPRINT_FRAME_LENGTH - FINGERPRINT_HOP_LENGTH,
        boundary="zeros",
        padded=True,
    )
    power = np.abs(stft_matrix).astype(np.float32) ** 2
    band_edges = np.geomspace(
        60.0, max(61.0, FINGERPRINT_SAMPLE_RATE / 2), FINGERPRINT_BAND_COUNT + 1
    )
    means: list[float] = []
    stds: list[float] = []
    for index in range(FINGERPRINT_BAND_COUNT):
        start_hz = band_edges[index]
        end_hz = band_edges[index + 1]
        band_mask = (frequencies >= start_hz) & (frequencies < end_hz)
        if not np.any(band_mask):
            band_series = np.zeros(power.shape[1], dtype=np.float32)
        else:
            band_series = power[band_mask].mean(axis=0).astype(np.float32, copy=False)
        log_series = np.log10(np.maximum(band_series, 1.0e-12))
        means.append(float(np.mean(log_series)))
        stds.append(float(np.std(log_series)))

    temporal_profile = np.log10(np.maximum(power.mean(axis=0), 1.0e-12))
    deltas = (
        np.diff(temporal_profile) if temporal_profile.size > 1 else np.zeros(1, dtype=np.float32)
    )
    histogram, _ = np.histogram(deltas, bins=FINGERPRINT_DELTA_BINS, range=(-0.5, 0.5))
    histogram = histogram.astype(np.float32)
    if float(histogram.sum()) > 0.0:
        histogram /= float(histogram.sum())
    features = np.asarray(means + stds + histogram.tolist(), dtype=np.float32)
    return base64.b64encode(features.astype(np.float16).tobytes()).decode("ascii")


def decode_reference_fingerprint(reference_fingerprint_b64: str) -> np.ndarray:
    raw = base64.b64decode(reference_fingerprint_b64)
    if not raw:
        return np.zeros(FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS, dtype=np.float32)
    return np.frombuffer(raw, dtype=np.float16).astype(np.float32)


def fingerprint_similarity(
    reference_fingerprint_b64: str, candidate_audio: np.ndarray, sample_rate: int
) -> float:
    reference = decode_reference_fingerprint(reference_fingerprint_b64)
    candidate = decode_reference_fingerprint(
        compute_reference_fingerprint(candidate_audio, sample_rate)
    )
    if reference.size == 0 or candidate.size == 0:
        return 0.0
    reference_norm = float(np.linalg.norm(reference))
    candidate_norm = float(np.linalg.norm(candidate))
    if reference_norm <= 0.0 or candidate_norm <= 0.0:
        return 0.0
    similarity = float(np.dot(reference, candidate) / (reference_norm * candidate_norm))
    return max(-1.0, min(1.0, similarity))


def build_sidecar_document(
    *,
    schema_version: int,
    payload: dict[str, object],
    signature_b64: str,
    public_key_b64: str,
    payload_sha256: str,
    key_id: str,
) -> dict[str, object]:
    return {
        "schema_version": int(schema_version),
        "key_id": str(key_id),
        "payload": payload,
        "signature_b64": signature_b64,
        "public_key_b64": public_key_b64,
        "payload_sha256": payload_sha256,
    }

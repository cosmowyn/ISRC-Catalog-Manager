import unittest
from unittest import mock

import numpy as np

from isrc_manager.authenticity import manifest as manifest_module
from isrc_manager.authenticity.manifest import (
    FINGERPRINT_BAND_COUNT,
    FINGERPRINT_DELTA_BINS,
    FINGERPRINT_FRAME_LENGTH,
    FINGERPRINT_SAMPLE_RATE,
    build_provenance_sidecar_document,
    build_sidecar_document,
    canonical_text,
    compute_reference_fingerprint,
    decode_reference_fingerprint,
    fingerprint_similarity,
    manifest_text,
)


class AuthenticityManifestHelperTests(unittest.TestCase):
    def test_manifest_text_uses_canonical_json_ordering(self):
        self.assertEqual(manifest_text({"track": "A", "index": 2}), '{"index":2,"track":"A"}')
        self.assertEqual(canonical_text({"track": "A", "index": 2}), '{"index":2,"track":"A"}')

    def test_reference_fingerprint_handles_empty_and_short_audio(self):
        expected_size = FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS

        fingerprints = [
            compute_reference_fingerprint(np.array([], dtype=np.float32), FINGERPRINT_SAMPLE_RATE),
            compute_reference_fingerprint(np.ones(32, dtype=np.float32), FINGERPRINT_SAMPLE_RATE),
        ]

        for fingerprint in fingerprints:
            with self.subTest(fingerprint=fingerprint):
                decoded = decode_reference_fingerprint(fingerprint)
                self.assertEqual(decoded.shape, (expected_size,))
                self.assertTrue(np.all(np.isfinite(decoded)))

    def test_reference_fingerprint_folds_stereo_at_target_sample_rate(self):
        left = np.linspace(-1.0, 1.0, FINGERPRINT_FRAME_LENGTH, dtype=np.float32)
        right = np.linspace(1.0, -1.0, FINGERPRINT_FRAME_LENGTH, dtype=np.float32)
        stereo = np.column_stack([left, right])

        decoded = decode_reference_fingerprint(
            compute_reference_fingerprint(stereo, FINGERPRINT_SAMPLE_RATE)
        )

        self.assertEqual(decoded.shape, (FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS,))
        self.assertTrue(np.all(np.isfinite(decoded)))

    def test_reference_fingerprint_resamples_non_target_sample_rate(self):
        audio = np.sin(np.linspace(0.0, np.pi * 4, 4096, dtype=np.float32))

        decoded = decode_reference_fingerprint(compute_reference_fingerprint(audio, 44100))

        self.assertEqual(decoded.shape, (FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS,))
        self.assertTrue(np.all(np.isfinite(decoded)))

    def test_reference_fingerprint_handles_empty_frequency_bands(self):
        fake_stft = (
            np.array([0.0, 10.0], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
            np.ones((2, 2), dtype=np.float32),
        )

        with mock.patch("isrc_manager.authenticity.manifest.signal.stft", return_value=fake_stft):
            decoded = decode_reference_fingerprint(
                compute_reference_fingerprint(
                    np.ones(FINGERPRINT_FRAME_LENGTH, dtype=np.float32),
                    FINGERPRINT_SAMPLE_RATE,
                )
            )

        self.assertEqual(decoded.shape, (FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS,))

    def test_reference_fingerprint_keeps_zero_delta_histogram(self):
        with mock.patch(
            "isrc_manager.authenticity.manifest.np.histogram",
            return_value=(
                np.zeros(FINGERPRINT_DELTA_BINS, dtype=np.int64),
                np.array([], dtype=np.float32),
            ),
        ):
            decoded = decode_reference_fingerprint(
                compute_reference_fingerprint(
                    np.ones(FINGERPRINT_FRAME_LENGTH, dtype=np.float32),
                    FINGERPRINT_SAMPLE_RATE,
                )
            )

        self.assertTrue(np.all(np.isfinite(decoded)))

    def test_decode_empty_reference_fingerprint_returns_zero_vector(self):
        decoded = decode_reference_fingerprint("")

        self.assertEqual(decoded.shape, (FINGERPRINT_BAND_COUNT * 2 + FINGERPRINT_DELTA_BINS,))
        self.assertTrue(np.array_equal(decoded, np.zeros_like(decoded)))

    def test_fingerprint_similarity_returns_zero_for_zero_norm_reference(self):
        similarity = fingerprint_similarity(
            "",
            np.ones(FINGERPRINT_FRAME_LENGTH, dtype=np.float32),
            FINGERPRINT_SAMPLE_RATE,
        )

        self.assertEqual(similarity, 0.0)

    def test_fingerprint_similarity_returns_zero_for_empty_vectors(self):
        with (
            mock.patch(
                "isrc_manager.authenticity.manifest.decode_reference_fingerprint",
                side_effect=[
                    np.array([], dtype=np.float32),
                    np.array([], dtype=np.float32),
                ],
            ),
            mock.patch(
                "isrc_manager.authenticity.manifest.compute_reference_fingerprint",
                return_value="ignored",
            ),
        ):
            similarity = manifest_module.fingerprint_similarity(
                "reference",
                np.ones(FINGERPRINT_FRAME_LENGTH, dtype=np.float32),
                FINGERPRINT_SAMPLE_RATE,
            )

        self.assertEqual(similarity, 0.0)

    def test_fingerprint_similarity_compares_matching_audio(self):
        audio = np.sin(np.linspace(0.0, np.pi * 8, FINGERPRINT_FRAME_LENGTH, dtype=np.float32))
        reference = compute_reference_fingerprint(audio, FINGERPRINT_SAMPLE_RATE)

        similarity = fingerprint_similarity(reference, audio, FINGERPRINT_SAMPLE_RATE)

        self.assertGreater(similarity, 0.99)
        self.assertLessEqual(similarity, 1.0)

    def test_sidecar_document_builders_normalize_header_fields(self):
        payload = {"track": "A"}

        sidecar = build_sidecar_document(
            schema_version="2",
            document_type=123,
            workflow_kind="direct",
            payload=payload,
            signature_b64="sig",
            public_key_b64="pub",
            payload_sha256="sha",
            key_id=456,
        )
        provenance = build_provenance_sidecar_document(
            schema_version="3",
            document_type="provenance",
            workflow_kind=789,
            key_id=101,
            parent_document={"id": "parent"},
            derivative_document={"id": "derivative"},
        )

        self.assertEqual(sidecar["schema_version"], 2)
        self.assertEqual(sidecar["document_type"], "123")
        self.assertIs(sidecar["payload"], payload)
        self.assertEqual(provenance["schema_version"], 3)
        self.assertEqual(provenance["workflow_kind"], "789")
        self.assertEqual(provenance["parent_document"], {"id": "parent"})


if __name__ == "__main__":
    unittest.main()

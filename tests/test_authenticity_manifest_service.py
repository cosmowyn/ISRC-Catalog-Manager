import json
import unittest

from isrc_manager.authenticity.crypto import (
    canonical_json_bytes,
    public_key_from_b64,
    sha256_hex,
    sign_bytes,
    verify_signature,
)
from isrc_manager.authenticity.manifest import manifest_bytes
from tests._authenticity_support import AuthenticityWorkflowTestCase


class AuthenticityManifestServiceTests(AuthenticityWorkflowTestCase):
    def test_manifest_bytes_are_deterministic_for_equivalent_payloads(self):
        payload = {
            "track_ref": {
                "track_id": 7,
                "isrc": "NLTST2600001",
            },
            "release_refs": [
                {"release_id": 1, "title": "Alpha"},
                {"release_id": 2, "title": "Beta"},
            ],
            "authenticity_version": 1,
        }

        encoded = manifest_bytes(payload)

        self.assertEqual(
            encoded,
            b'{"authenticity_version":1,"release_refs":[{"release_id":1,"title":"Alpha"},{"release_id":2,"title":"Beta"}],"track_ref":{"isrc":"NLTST2600001","track_id":7}}',
        )
        self.assertEqual(encoded, canonical_json_bytes(json.loads(encoded.decode("utf-8"))))

    def test_ed25519_sign_and_verify_round_trip(self):
        record, private_key, _watermark_key = self.key_service.signing_material()
        payload = manifest_bytes({"manifest_id": "abc123", "track_id": 99})
        signature_b64 = sign_bytes(private_key, payload)

        self.assertTrue(
            verify_signature(
                public_key_from_b64(record.public_key_b64),
                payload,
                signature_b64,
            )
        )
        self.assertFalse(
            verify_signature(
                public_key_from_b64(record.public_key_b64),
                payload + b"!",
                signature_b64,
            )
        )

    def test_prepare_manifest_signs_payload_for_verify_only_mode(self):
        track_id, _audio_path = self.create_track_with_audio(duration_seconds=30, seed=1)

        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )

        self.assertEqual(
            prepared.payload_sha256,
            sha256_hex(manifest_bytes(prepared.payload)),
        )
        self.assertEqual(
            prepared.payload["watermark_binding"]["manifest_digest_prefix"],
            prepared.watermark_token.manifest_digest_prefix,
        )
        self.assertTrue(
            verify_signature(
                public_key_from_b64(prepared.public_key_b64),
                manifest_bytes(prepared.payload),
                prepared.signature_b64,
            )
        )

    def test_save_manifest_persists_expected_binding_columns(self):
        track_id, _audio_path = self.create_track_with_audio(duration_seconds=30, seed=2)
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )

        record = self.manifest_service.save_manifest(prepared)
        reloaded = self.manifest_service.fetch_manifest_by_manifest_id(record.manifest_id)

        self.assertIsNotNone(reloaded)
        self.assertEqual(record.manifest_id, prepared.payload["manifest_id"])
        self.assertEqual(record.watermark_id, prepared.watermark_token.watermark_id)
        self.assertEqual(
            record.manifest_digest_prefix, prepared.watermark_token.manifest_digest_prefix
        )
        self.assertEqual(record.reference_audio_sha256, prepared.reference.sha256_hex)


if __name__ == "__main__":
    unittest.main()

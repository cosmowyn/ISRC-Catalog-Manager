import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from isrc_manager.assets import AssetVersionPayload
from isrc_manager.authenticity.crypto import (
    canonical_json_bytes,
    public_key_from_b64,
    sha256_hex,
    sign_bytes,
    verify_signature,
)
from isrc_manager.authenticity.manifest import manifest_bytes
from isrc_manager.authenticity.models import ReferenceAudioSelection
from isrc_manager.authenticity.service import (
    AuthenticityKeyService,
    _report_progress_stage,
    _signed_document_is_valid,
    _watermark_token_from_payload,
)
from isrc_manager.releases import ReleasePayload, ReleaseTrackPlacement
from isrc_manager.services.tracks import TrackCreatePayload
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

    def test_helper_edges_reject_bad_progress_signed_document_and_watermark_payloads(self):
        _report_progress_stage(
            None,
            item_index=1,
            item_total=1,
            stage_index=0,
            stage_count=1,
            message="ignored",
        )
        progress_updates: list[tuple[int, int, str]] = []

        _report_progress_stage(
            lambda value, maximum, message: progress_updates.append((value, maximum, message)),
            base_value=5,
            item_index=2,
            item_total=3,
            stage_index=1,
            stage_count=4,
            message="working",
        )

        self.assertEqual(progress_updates, [(10, 17, "working")])
        self.assertFalse(_signed_document_is_valid({"payload": {"manifest_id": "missing-key"}}))
        track_id, _audio_path = self.create_track_with_audio(duration_seconds=30, seed=3)
        prepared = self.manifest_service.prepare_manifest(
            track_id=track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        document = {
            "payload": prepared.payload,
            "signature_b64": prepared.signature_b64,
            "public_key_b64": prepared.public_key_b64,
            "payload_sha256": prepared.payload_sha256,
        }
        self.assertTrue(_signed_document_is_valid(document))
        self.assertFalse(_signed_document_is_valid({**document, "payload_sha256": "0" * 64}))
        with mock.patch(
            "isrc_manager.authenticity.service.public_key_from_b64",
            side_effect=ValueError("corrupt public key"),
        ):
            self.assertFalse(_signed_document_is_valid(document))

        self.assertIsNone(
            _watermark_token_from_payload({"watermark_binding": {"watermark_id": "bad-int"}})
        )
        self.assertIsNone(
            _watermark_token_from_payload(
                {
                    "watermark_binding": {
                        "watermark_id": 1,
                        "watermark_nonce": 2,
                        "manifest_digest_prefix": "short",
                    }
                }
            )
        )
        self.assertEqual(
            _watermark_token_from_payload(prepared.payload).watermark_id,
            prepared.watermark_token.watermark_id,
        )

    def test_key_service_guardrails_cover_default_missing_and_corrupt_key_paths(self):
        default_profile_service = AuthenticityKeyService(self.conn)
        with self.assertRaisesRegex(ValueError, "Settings root is not configured"):
            _private_key_dir = default_profile_service.private_key_dir

        self.assertEqual(
            self.key_service.public_key_bytes_for(self.default_key.key_id),
            self.default_key.public_key_b64,
        )
        with mock.patch.object(self.key_service, "fetch_key", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "could not be reloaded"):
                self.key_service.generate_keypair(signer_label="Reload Failure")

        self.key_service.set_default_key("")
        with self.assertRaisesRegex(ValueError, "Generate an Audio Authenticity key"):
            self.key_service.resolve_key()

        self.key_service.set_default_key("missing-key")
        with self.assertRaisesRegex(ValueError, "missing-key"):
            self.key_service.resolve_key()

        self.key_service.set_default_key(self.default_key.key_id)
        second_key = self.key_service.generate_keypair(signer_label="Secondary Signer")
        self.assertFalse(second_key.is_default)
        private_path = self.key_service.private_key_path(second_key.key_id)
        private_path.unlink()
        with self.assertRaisesRegex(FileNotFoundError, second_key.key_id):
            self.key_service.load_private_key(second_key.key_id)
        self.assertNotIn(
            second_key.key_id,
            [key_id for key_id, _watermark_key in self.key_service.extraction_keys()],
        )

        corrupt_key = self.key_service.generate_keypair(signer_label="Corrupt Signer")
        self.key_service.private_key_path(corrupt_key.key_id).write_text(
            "not a private key",
            encoding="utf-8",
        )
        self.assertNotIn(
            corrupt_key.key_id,
            [key_id for key_id, _watermark_key in self.key_service.extraction_keys()],
        )

    def test_reference_selection_edges_cover_missing_unsupported_and_payload_resolution(self):
        track_id, audio_path = self.create_track_with_audio(duration_seconds=30, seed=4)

        with self.assertRaisesRegex(FileNotFoundError, "Asset 9999"):
            self.manifest_service._reference_selection_from_asset(track_id, 9999)
        with self.assertRaisesRegex(ValueError, "Track 9999"):
            self.manifest_service._reference_selection_from_track_audio(9999)
        with self.assertRaises(FileNotFoundError):
            self.manifest_service.reference_selection_from_file(
                track_id=track_id,
                source_path=self.root / "missing.wav",
                source_kind="manual",
                source_label="Missing",
            )

        unsupported_file = self.root / "notes.txt"
        unsupported_file.write_text("not audio", encoding="utf-8")
        unsupported_asset_id = self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(unsupported_file),
                approved_for_use=True,
                primary_flag=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "reference asset"):
            self.manifest_service._reference_selection_from_asset(track_id, unsupported_asset_id)
        with self.assertRaisesRegex(ValueError, "reference file"):
            self.manifest_service.reference_selection_from_file(
                track_id=track_id,
                source_path=unsupported_file,
                source_kind="manual",
                source_label="Unsupported",
            )
        unsupported_candidate = SimpleNamespace(
            id=unsupported_asset_id,
            asset_type="main_master",
            approved_for_use=True,
            primary_flag=True,
            filename="preview.mp3",
            stored_path=None,
        )
        with mock.patch.object(
            self.asset_service,
            "list_assets",
            return_value=[unsupported_candidate],
        ):
            self.assertEqual(
                self.manifest_service.select_reference_audio(track_id).source_kind,
                "track_audio",
            )

        asset_audio = self.write_audio_fixture(
            "approved-master.wav",
            duration_seconds=30,
            seed=5,
            suffix=".wav",
        )
        supported_asset_id = self.asset_service.create_asset(
            AssetVersionPayload(
                track_id=track_id,
                asset_type="main_master",
                source_path=str(asset_audio),
                approved_for_use=True,
                primary_flag=False,
            )
        )
        self.assertEqual(
            self.manifest_service.resolve_reference_for_payload(
                {
                    "reference_audio": {
                        "source_kind": "asset",
                        "source_track_id": track_id,
                        "reference_asset_id": supported_asset_id,
                    }
                }
            ).source_kind,
            "asset",
        )
        track_audio_selection = self.manifest_service.resolve_reference_for_payload(
            {
                "reference_audio": {
                    "source_kind": "track_audio",
                    "source_track_id": track_id,
                }
            }
        )
        self.assertEqual(track_audio_selection.source_kind, "track_audio")
        self.assertTrue(track_audio_selection.source_path.exists())
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {"reference_audio": {"source_track_id": object(), "source_kind": "asset"}}
            )
        )
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {
                    "reference_audio": {
                        "source_kind": "asset",
                        "source_track_id": track_id,
                        "reference_asset_id": "bad-int",
                    }
                }
            )
        )
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {"reference_audio": {"source_track_id": track_id}}
            )
        )

        with (
            mock.patch.object(
                self.release_service, "find_release_ids_for_track", return_value=[12345]
            ),
            mock.patch.object(self.release_service, "fetch_release", return_value=None),
        ):
            self.assertEqual(self.manifest_service._build_release_refs(track_id), [])

        source_bytes_reference = self.manifest_service.reference_selection_from_file(
            track_id=track_id,
            source_path=audio_path,
            source_kind="manual",
            source_label="Manual bytes",
        )
        source_bytes_reference.source_bytes = audio_path.read_bytes()
        source_bytes_reference.source_path = None
        source_bytes_reference.sha256_hex = None
        prepared = self.manifest_service._prepare_manifest_from_reference(
            track_id=track_id,
            reference=source_bytes_reference,
            key_id=None,
            app_version="test-app",
            profile_name="Test Profile",
            workflow_kind="manual_reference",
        )
        self.assertEqual(prepared.reference.source_kind, "manual")
        self.assertEqual(prepared.reference.sha256_hex, sha256_hex(audio_path.read_bytes()))

    def test_manifest_preparation_edges_reject_missing_tracks_unreadable_references_and_no_source(
        self,
    ):
        empty_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-99997",
                track_title="No Authenticity Source",
                artist_name="Moonwake",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=0,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        with self.assertRaisesRegex(ValueError, "No supported WAV"):
            self.manifest_service.select_reference_audio(empty_track_id)

        unreadable_reference = ReferenceAudioSelection(
            track_id=empty_track_id,
            source_kind="manual",
            source_label="Unreadable",
            reference_asset_id=None,
            filename="unreadable.wav",
            mime_type="audio/wav",
            size_bytes=0,
            suffix=".wav",
        )
        with self.assertRaisesRegex(ValueError, "Track 999999"):
            self.manifest_service._prepare_manifest_from_reference(
                track_id=999999,
                reference=unreadable_reference,
                key_id=None,
                app_version="test-app",
                profile_name="Test Profile",
                workflow_kind="manual_reference",
            )
        with self.assertRaisesRegex(ValueError, "Reference audio could not be read"):
            self.manifest_service._prepare_manifest_from_reference(
                track_id=empty_track_id,
                reference=unreadable_reference,
                key_id=None,
                app_version="test-app",
                profile_name="Test Profile",
                workflow_kind="manual_reference",
            )
        unreadable_reference.sample_rate = 22050
        self.assertEqual(self.manifest_service._reference_sample_rate(unreadable_reference), 22050)

    def test_audio_authenticity_helpers_cover_tagging_attached_audio_and_lineage_edges(self):
        track_id, _audio_path = self.create_track_with_audio(
            title="Tag Context Track",
            album_title="Tag Album",
            duration_seconds=30,
            seed=6,
        )

        self.assertEqual(self.audio_service._normalized_text("  Tag Album  "), "tag album")
        self.assertEqual(
            self.audio_service._select_tag_release_context(
                track_id=track_id,
                snapshot_album_title="No Release",
            ),
            (None, None, None),
        )

        first_release_id = self.release_service.create_release(
            ReleasePayload(
                title="Tag Album",
                primary_artist="Moonwake",
                album_artist="Moonwake Ensemble",
                release_date="2026-03-24",
                label="Northern Current",
                upc="4006381333931",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=2,
                        track_number=5,
                        sequence_number=1,
                    )
                ],
            )
        )
        release_values, placement_values, artwork = self.audio_service._select_tag_release_context(
            track_id=track_id,
            snapshot_album_title="Tag Album",
        )
        self.assertEqual(release_values["title"], "Tag Album")
        self.assertEqual(placement_values, {"track_number": 5, "disc_number": 2})
        self.assertIsNone(artwork)

        self.release_service.create_release(
            ReleasePayload(
                title="Alternate Album",
                primary_artist="Moonwake",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=2,
                    )
                ],
            )
        )
        self.assertEqual(
            self.audio_service._select_tag_release_context(
                track_id=track_id,
                snapshot_album_title="Tag Album",
            )[0]["title"],
            "Tag Album",
        )
        self.assertEqual(
            self.audio_service._select_tag_release_context(
                track_id=track_id,
                snapshot_album_title="Missing Album",
            ),
            (None, None, None),
        )
        with (
            mock.patch.object(
                self.manifest_service,
                "_build_release_refs",
                return_value=[{"release_id": first_release_id, "title": "Ghost Album"}],
            ),
            mock.patch.object(self.release_service, "fetch_release", return_value=None),
        ):
            self.assertEqual(
                self.audio_service._select_tag_release_context(
                    track_id=track_id,
                    snapshot_album_title="Ghost Album",
                ),
                (None, None, None),
            )

        fake_release = SimpleNamespace(
            title="Artwork Album",
            primary_artist="Moonwake",
            album_artist="Moonwake Ensemble",
            release_date="2026-03-24",
            label="Northern Current",
            upc="4006381333931",
            artwork_path="missing-cover.jpg",
            artwork_filename="missing-cover.jpg",
        )
        fake_placement = SimpleNamespace(track_id=track_id, disc_number=1, track_number=9)
        with (
            mock.patch.object(
                self.manifest_service,
                "_build_release_refs",
                return_value=[{"release_id": first_release_id, "title": "Artwork Album"}],
            ),
            mock.patch.object(
                self.release_service,
                "fetch_release",
                return_value=fake_release,
            ),
            mock.patch.object(
                self.release_service,
                "list_release_tracks",
                return_value=[fake_placement],
            ),
            mock.patch.object(
                self.release_service,
                "fetch_artwork_bytes",
                side_effect=FileNotFoundError("cover missing"),
            ),
        ):
            _release_values, _placement_values, artwork = (
                self.audio_service._select_tag_release_context(
                    track_id=track_id,
                    snapshot_album_title="Artwork Album",
                )
            )
        self.assertIsNone(artwork)

        empty_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-99998",
                track_title="Empty Audio",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Tag Album",
                release_date="2026-03-24",
                track_length_sec=0,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        with self.assertRaisesRegex(ValueError, "Track 999999"):
            self.audio_service._attached_audio_source(999999)
        with self.assertRaisesRegex(ValueError, "No attached track audio"):
            self.audio_service._attached_audio_source(empty_track_id)

        self.track_service.convert_media_storage_mode(track_id, "audio_file", "database")
        attached_source = self.audio_service._attached_audio_source(track_id)
        self.assertIsNone(attached_source["source_path"])
        self.assertGreater(len(attached_source["source_bytes"]), 0)
        self.assertIsNone(self.audio_service._payload_watermark_id({}))
        self.assertIsNone(
            self.audio_service._payload_watermark_id(
                {"watermark_binding": {"watermark_id": "bad-int"}}
            )
        )
        self.assertEqual(
            self.audio_service._payload_watermark_id({"watermark_binding": {"watermark_id": 42}}),
            42,
        )

        lineage_track_id, _lineage_audio_path = self.create_track_with_audio(
            title="Lineage Track",
            album_title="Lineage Album",
            duration_seconds=30,
            seed=7,
        )
        with self.assertRaisesRegex(ValueError, "No direct authenticity manifest"):
            self.audio_service._direct_manifest_ready_for_lineage(lineage_track_id)
        prepared = self.manifest_service.prepare_manifest(
            track_id=lineage_track_id,
            app_version="test-app",
            profile_name="Test Profile",
        )
        record = self.manifest_service.save_manifest(prepared)
        self.conn.execute(
            "UPDATE AuthenticityManifests SET reference_audio_sha256=? WHERE id=?",
            ("bad-sha", record.id),
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.audio_service._direct_manifest_ready_for_lineage(lineage_track_id)
        with self.assertRaisesRegex(ValueError, "missing-parent-key"):
            self.audio_service._build_parent_direct_document(
                replace(record, key_id="missing-parent-key")
            )

    def test_export_plan_edges_record_missing_invalid_and_unsupported_tracks(self):
        unsupported_track_id, _unsupported_audio = self.create_track_with_audio(
            title="Unsupported Direct Source",
            duration_seconds=30,
            seed=8,
            suffix=".mp3",
        )
        progress_updates: list[tuple[int, int, str]] = []

        plan = self.audio_service.build_export_plan(
            ["not-an-id", 999999, unsupported_track_id],
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.items[0].status, "unsupported")
        self.assertIn("Track 999999 no longer exists", plan.warnings[0])
        self.assertIn("Attached track audio is not a WAV", plan.warnings[1])
        self.assertEqual(len(progress_updates), 1)

        provenance_plan = self.audio_service.build_provenance_export_plan(
            ["not-an-id", 999999, unsupported_track_id],
            progress_callback=lambda value, maximum, message: progress_updates.append(
                (value, maximum, message)
            ),
        )
        self.assertEqual(provenance_plan.items[0].status, "unsupported")
        self.assertIn("Track 999999 no longer exists", provenance_plan.warnings[0])
        self.assertIn("No direct authenticity manifest", provenance_plan.warnings[-1])

        with self.assertRaisesRegex(ValueError, "Reference audio is missing"):
            self.manifest_service._decode_reference_audio(
                ReferenceAudioSelection(
                    track_id=unsupported_track_id,
                    source_kind="manual",
                    source_label="Missing bytes",
                    reference_asset_id=None,
                    filename="missing.wav",
                    mime_type="audio/wav",
                    size_bytes=0,
                    suffix=".wav",
                )
            )

    def test_manifest_service_covers_rights_reference_rate_and_payload_resolution_edges(self):
        track_id, audio_path = self.create_track_with_audio(duration_seconds=30, seed=41)

        class RightsService:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def list_rights(self, *, entity_type, entity_id):
                self.calls.append((entity_type, int(entity_id)))
                return [SimpleNamespace(id={"track": 3, "work": 1, "release": 2}[entity_type])]

            def ownership_summary(self, *, entity_type, entity_id):
                return SimpleNamespace(
                    master_control={f"{entity_type}-{entity_id}-master"},
                    publishing_control={f"{entity_type}-{entity_id}-publishing"},
                    exclusive_territories={f"{entity_type}-{entity_id}-territory"},
                )

        rights_service = RightsService()
        self.manifest_service.rights_service = rights_service
        summary = self.manifest_service._build_rights_summary(
            track_id,
            [{"work_id": 11, "title": "Work"}],
            [{"release_id": 22, "title": "Release"}],
        )
        self.assertEqual(summary["right_ids"], [1, 2, 3])
        self.assertEqual(
            rights_service.calls,
            [("track", track_id), ("work", 11), ("release", 22)],
        )
        self.assertEqual(
            summary["release_control"][0]["master_control"],
            {"release-22-master"},
        )

        reference = ReferenceAudioSelection(
            track_id=track_id,
            source_kind="track_audio",
            source_label="Track audio",
            reference_asset_id=None,
            filename=audio_path.name,
            mime_type="audio/wav",
            size_bytes=audio_path.stat().st_size,
            suffix=".wav",
            source_bytes=audio_path.read_bytes(),
            sample_rate=None,
        )
        self.assertEqual(self.manifest_service._reference_sample_rate(reference), 44100)
        self.assertEqual(reference.sample_rate, 44100)

        self.assertIsNone(self.manifest_service.resolve_reference_for_payload({}))
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {
                    "track_ref": {"track_id": "not-an-int"},
                    "reference_audio": {"source_kind": "track_audio"},
                }
            )
        )
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {
                    "track_ref": {"track_id": track_id},
                    "reference_audio": {
                        "source_kind": "asset",
                        "reference_asset_id": 0,
                    },
                }
            )
        )
        self.assertIsNone(
            self.manifest_service.resolve_reference_for_payload(
                {
                    "track_ref": {"track_id": track_id},
                    "reference_audio": {"source_kind": "missing-kind"},
                }
            )
        )
        self.assertIn("sync_word_hex", self.audio_service.watermark_service.settings_payload())

    def test_direct_lineage_reference_hash_recovery_and_missing_bytes_edges(self):
        track_id, audio_path, _result = self.export_direct_authenticity_fixture(seed=42)
        manifest_record = self.manifest_service.fetch_latest_manifest_for_track(track_id)
        self.assertIsNotNone(manifest_record)
        assert manifest_record is not None

        reference = ReferenceAudioSelection(
            track_id=track_id,
            source_kind="track_audio",
            source_label="Track audio",
            reference_asset_id=None,
            filename=audio_path.name,
            mime_type="audio/wav",
            size_bytes=audio_path.stat().st_size,
            suffix=".wav",
            source_path=audio_path,
            sha256_hex=None,
        )
        with mock.patch.object(
            self.manifest_service,
            "select_reference_audio",
            return_value=reference,
        ):
            ready_manifest, _payload, ready_reference = (
                self.audio_service._direct_manifest_ready_for_lineage(track_id)
            )
        self.assertEqual(ready_manifest.id, manifest_record.id)
        self.assertEqual(ready_reference.sha256_hex, manifest_record.reference_audio_sha256)

        missing_reference = replace(reference, source_path=None, source_bytes=None, sha256_hex=None)
        with mock.patch.object(
            self.manifest_service,
            "select_reference_audio",
            return_value=missing_reference,
        ):
            with self.assertRaisesRegex(ValueError, "could not be read"):
                self.audio_service._direct_manifest_ready_for_lineage(track_id)


if __name__ == "__main__":
    unittest.main()

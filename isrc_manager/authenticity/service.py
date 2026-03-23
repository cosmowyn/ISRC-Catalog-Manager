"""Authenticity services spanning keys, manifests, watermarking, and verification."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from isrc_manager.assets import AssetService
from isrc_manager.file_storage import sanitize_export_basename
from isrc_manager.releases import ReleaseService
from isrc_manager.rights import RightsService
from isrc_manager.services.session import ProfileKVService
from isrc_manager.services.tracks import TrackService
from isrc_manager.tags import ArtworkPayload, AudioTagService, catalog_metadata_to_tags
from isrc_manager.works import WorkService

from .crypto import (
    canonical_timestamp,
    derive_watermark_key,
    generate_private_key,
    key_id_for_public_key,
    load_private_key,
    public_key_b64,
    public_key_from_b64,
    sha256_hex,
    sign_bytes,
    verify_signature,
    write_private_key,
)
from .manifest import (
    build_sidecar_document,
    canonical_text,
    compute_reference_fingerprint,
    fingerprint_similarity,
    manifest_bytes,
)
from .models import (
    AUTHENTICITY_SCHEMA_VERSION,
    SUPPORTED_AUTHENTICITY_SUFFIXES,
    VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH,
    VERIFICATION_STATUS_NO_WATERMARK,
    VERIFICATION_STATUS_SIGNATURE_INVALID,
    VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    VERIFICATION_STATUS_VERIFIED,
    WATERMARK_VERSION,
    AuthenticityExportPlan,
    AuthenticityExportPlanItem,
    AuthenticityExportResult,
    AuthenticityKeyRecord,
    AuthenticityManifestRecord,
    AuthenticityVerificationReport,
    PreparedAuthenticityManifest,
    ReferenceAudioSelection,
    WatermarkToken,
)
from .watermark import AudioWatermarkCore, supported_audio_path, watermark_settings_payload

DEFAULT_KEY_ID_KV = "authenticity/default_key_id"


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class AuthenticityKeyService:
    """Owns Ed25519 public-key registry rows and local private-key files."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        profile_kv: ProfileKVService | None = None,
        settings_root: str | Path | None = None,
    ):
        self.conn = conn
        self.profile_kv = profile_kv or ProfileKVService(conn)
        self.settings_root = Path(settings_root) if settings_root is not None else None
        self.profile_kv.ensure_store()

    @property
    def private_key_dir(self) -> Path:
        if self.settings_root is None:
            raise ValueError("Settings root is not configured for authenticity keys.")
        return self.settings_root / "keys" / "ed25519"

    def private_key_path(self, key_id: str) -> Path:
        return self.private_key_dir / f"{key_id}.pem"

    def default_key_id(self) -> str | None:
        return _clean_text(self.profile_kv.get(DEFAULT_KEY_ID_KV))

    def set_default_key(self, key_id: str) -> None:
        self.profile_kv.set(DEFAULT_KEY_ID_KV, key_id)

    def _row_to_key_record(self, row) -> AuthenticityKeyRecord:
        key_id = str(row[0] or "")
        return AuthenticityKeyRecord(
            key_id=key_id,
            algorithm=str(row[1] or "ed25519"),
            signer_label=_clean_text(row[2]),
            public_key_b64=str(row[3] or ""),
            created_at=_clean_text(row[4]),
            retired_at=_clean_text(row[5]),
            notes=_clean_text(row[6]),
            has_private_key=self.private_key_path(key_id).exists() if self.settings_root else False,
            is_default=(key_id == self.default_key_id()),
        )

    def list_keys(self) -> list[AuthenticityKeyRecord]:
        rows = self.conn.execute(
            """
            SELECT key_id, algorithm, signer_label, public_key_b64, created_at, retired_at, notes
            FROM AuthenticityKeys
            ORDER BY created_at, key_id
            """
        ).fetchall()
        return [self._row_to_key_record(row) for row in rows]

    def fetch_key(self, key_id: str) -> AuthenticityKeyRecord | None:
        row = self.conn.execute(
            """
            SELECT key_id, algorithm, signer_label, public_key_b64, created_at, retired_at, notes
            FROM AuthenticityKeys
            WHERE key_id=?
            """,
            (str(key_id),),
        ).fetchone()
        return self._row_to_key_record(row) if row else None

    def resolve_key(self, key_id: str | None = None) -> AuthenticityKeyRecord:
        chosen_key_id = _clean_text(key_id) or self.default_key_id()
        if not chosen_key_id:
            raise ValueError(
                "Generate an Audio Authenticity key first, then choose it as the default signing key."
            )
        record = self.fetch_key(chosen_key_id)
        if record is None:
            raise ValueError(f"Authenticity key '{chosen_key_id}' was not found.")
        return record

    def generate_keypair(
        self, *, signer_label: str | None = None, notes: str | None = None
    ) -> AuthenticityKeyRecord:
        private_key = generate_private_key()
        public_key = private_key.public_key()
        key_id = key_id_for_public_key(public_key)
        write_private_key(private_key, self.private_key_path(key_id))
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO AuthenticityKeys(
                    key_id,
                    algorithm,
                    signer_label,
                    public_key_b64,
                    created_at,
                    retired_at,
                    notes
                )
                VALUES (?, 'ed25519', ?, ?, datetime('now'), NULL, ?)
                """,
                (
                    key_id,
                    _clean_text(signer_label),
                    public_key_b64(public_key),
                    _clean_text(notes),
                ),
            )
        if not self.default_key_id():
            self.set_default_key(key_id)
        record = self.fetch_key(key_id)
        if record is None:
            raise RuntimeError("Key was created but could not be reloaded from the database.")
        return record

    def public_key_bytes_for(self, key_id: str) -> str:
        record = self.resolve_key(key_id)
        return record.public_key_b64

    def load_private_key(self, key_id: str):
        path = self.private_key_path(key_id)
        if not path.exists():
            raise FileNotFoundError(f"Private key file is missing for '{key_id}'.")
        return load_private_key(path)

    def signing_material(
        self, key_id: str | None = None
    ) -> tuple[AuthenticityKeyRecord, object, bytes]:
        record = self.resolve_key(key_id)
        private_key = self.load_private_key(record.key_id)
        watermark_key = derive_watermark_key(private_key)
        return record, private_key, watermark_key

    def extraction_keys(self) -> list[tuple[str, bytes]]:
        ordered = self.list_keys()
        default_key_id = self.default_key_id()
        if default_key_id:
            ordered.sort(key=lambda item: (0 if item.key_id == default_key_id else 1, item.key_id))
        result: list[tuple[str, bytes]] = []
        for record in ordered:
            path = self.private_key_path(record.key_id)
            if not path.exists():
                continue
            try:
                result.append((record.key_id, derive_watermark_key(load_private_key(path))))
            except Exception:
                continue
        return result


class AuthenticityManifestService:
    """Builds and stores signed authenticity manifests."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        track_service: TrackService,
        release_service: ReleaseService,
        work_service: WorkService,
        rights_service: RightsService,
        asset_service: AssetService,
        key_service: AuthenticityKeyService,
    ):
        self.conn = conn
        self.track_service = track_service
        self.release_service = release_service
        self.work_service = work_service
        self.rights_service = rights_service
        self.asset_service = asset_service
        self.key_service = key_service

    def _suffix_for(self, filename: str | None) -> str:
        suffix = Path(str(filename or "")).suffix.lower()
        return suffix

    def _reference_selection_from_asset(
        self, track_id: int, asset_id: int
    ) -> ReferenceAudioSelection:
        asset = self.asset_service.fetch_asset(asset_id)
        if asset is None:
            raise FileNotFoundError(f"Asset {asset_id} not found.")
        data, mime_type = self.asset_service.fetch_asset_bytes(asset_id)
        suffix = self._suffix_for(asset.filename or asset.stored_path)
        if suffix not in SUPPORTED_AUTHENTICITY_SUFFIXES:
            raise ValueError("Selected reference asset is not a WAV or FLAC file.")
        return ReferenceAudioSelection(
            track_id=int(track_id),
            source_kind="asset",
            source_label=f"{asset.asset_type}: {asset.filename}",
            reference_asset_id=int(asset.id),
            filename=str(asset.filename or f"asset-{asset.id}{suffix}"),
            mime_type=_clean_text(mime_type),
            size_bytes=len(data),
            suffix=suffix,
            source_path=self.asset_service.resolve_asset_path(asset.stored_path),
            source_bytes=None if self.asset_service.resolve_asset_path(asset.stored_path) else data,
            sample_rate=asset.sample_rate,
            bit_depth=asset.bit_depth,
            format_name=_clean_text(asset.format),
            sha256_hex=sha256_hex(data),
        )

    def _reference_selection_from_track_audio(self, track_id: int) -> ReferenceAudioSelection:
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is None:
            raise ValueError(f"Track {track_id} not found.")
        suffix = self._suffix_for(snapshot.audio_file_filename or snapshot.audio_file_path)
        if suffix not in SUPPORTED_AUTHENTICITY_SUFFIXES:
            raise ValueError("Attached track audio is not a WAV or FLAC file.")
        data, mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")
        return ReferenceAudioSelection(
            track_id=int(track_id),
            source_kind="track_audio",
            source_label="Attached track audio",
            reference_asset_id=None,
            filename=str(snapshot.audio_file_filename or f"track-{track_id}{suffix}"),
            mime_type=_clean_text(mime_type),
            size_bytes=len(data),
            suffix=suffix,
            source_path=self.track_service.resolve_media_path(snapshot.audio_file_path),
            source_bytes=(
                None if self.track_service.resolve_media_path(snapshot.audio_file_path) else data
            ),
            sha256_hex=sha256_hex(data),
        )

    def select_reference_audio(self, track_id: int) -> ReferenceAudioSelection:
        candidates = [
            asset
            for asset in self.asset_service.list_assets(track_id=track_id)
            if asset.asset_type in {"main_master", "hi_res_master"} and asset.approved_for_use
        ]
        candidates.sort(
            key=lambda item: (
                0 if item.primary_flag else 1,
                0 if item.asset_type == "main_master" else 1,
                item.id,
            )
        )
        for asset in candidates:
            suffix = self._suffix_for(asset.filename or asset.stored_path)
            if suffix in SUPPORTED_AUTHENTICITY_SUFFIXES:
                return self._reference_selection_from_asset(track_id, asset.id)
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is not None and self.track_service.has_media(track_id, "audio_file"):
            return self._reference_selection_from_track_audio(track_id)
        raise ValueError(
            "No supported WAV or FLAC reference audio was found. V1 uses approved main/hi-res masters first, then attached track audio."
        )

    def _build_release_refs(self, track_id: int) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        for release_id in self.release_service.find_release_ids_for_track(track_id):
            release = self.release_service.fetch_release(release_id)
            if release is None:
                continue
            refs.append(
                {
                    "release_id": int(release.id),
                    "title": release.title,
                    "upc": release.upc,
                    "catalog_number": release.catalog_number,
                    "release_date": release.release_date,
                    "profile_name": release.profile_name,
                }
            )
        refs.sort(key=lambda item: (int(item["release_id"]), str(item.get("title") or "")))
        return refs

    def _build_work_refs(self, track_id: int) -> list[dict[str, object]]:
        refs = [
            {
                "work_id": int(work.id),
                "title": work.title,
                "iswc": work.iswc,
                "registration_number": work.registration_number,
                "profile_name": work.profile_name,
            }
            for work in self.work_service.list_works_for_track(track_id)
        ]
        refs.sort(key=lambda item: (int(item["work_id"]), str(item.get("title") or "")))
        return refs

    def _build_rights_summary(
        self,
        track_id: int,
        work_refs: list[dict[str, object]],
        release_refs: list[dict[str, object]],
    ) -> dict[str, object]:
        rights = {
            item.id: item
            for item in self.rights_service.list_rights(entity_type="track", entity_id=track_id)
        }
        for work_ref in work_refs:
            for item in self.rights_service.list_rights(
                entity_type="work", entity_id=int(work_ref["work_id"])
            ):
                rights[item.id] = item
        for release_ref in release_refs:
            for item in self.rights_service.list_rights(
                entity_type="release", entity_id=int(release_ref["release_id"])
            ):
                rights[item.id] = item
        ordered_rights = [rights[key] for key in sorted(rights)]
        track_ownership = self.rights_service.ownership_summary(
            entity_type="track", entity_id=track_id
        )
        release_ownership = [
            {
                "release_id": int(release_ref["release_id"]),
                "master_control": self.rights_service.ownership_summary(
                    entity_type="release",
                    entity_id=int(release_ref["release_id"]),
                ).master_control,
                "publishing_control": self.rights_service.ownership_summary(
                    entity_type="release",
                    entity_id=int(release_ref["release_id"]),
                ).publishing_control,
            }
            for release_ref in release_refs
        ]
        work_ownership = [
            {
                "work_id": int(work_ref["work_id"]),
                "master_control": self.rights_service.ownership_summary(
                    entity_type="work",
                    entity_id=int(work_ref["work_id"]),
                ).master_control,
                "publishing_control": self.rights_service.ownership_summary(
                    entity_type="work",
                    entity_id=int(work_ref["work_id"]),
                ).publishing_control,
            }
            for work_ref in work_refs
        ]
        return {
            "right_ids": [int(item.id) for item in ordered_rights],
            "track_control": {
                "master_control": sorted(track_ownership.master_control),
                "publishing_control": sorted(track_ownership.publishing_control),
                "exclusive_territories": sorted(track_ownership.exclusive_territories),
            },
            "release_control": release_ownership,
            "work_control": work_ownership,
        }

    def prepare_manifest(
        self,
        *,
        track_id: int,
        key_id: str | None = None,
        app_version: str,
        profile_name: str | None,
    ) -> PreparedAuthenticityManifest:
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is None:
            raise ValueError(f"Track {track_id} not found.")
        key_record, private_key, _watermark_key = self.key_service.signing_material(key_id)
        reference = self.select_reference_audio(track_id)
        reference_bytes = (
            bytes(reference.source_bytes)
            if reference.source_bytes is not None
            else (
                Path(reference.source_path).read_bytes()
                if reference.source_path is not None
                else None
            )
        )
        if reference_bytes is None:
            raise ValueError("Reference audio could not be read.")
        reference.sha256_hex = reference.sha256_hex or sha256_hex(reference_bytes)
        reference.fingerprint_b64 = compute_reference_fingerprint(
            audio=self._decode_reference_audio(reference),
            sample_rate=self._reference_sample_rate(reference),
        )
        watermark_id = int(secrets.randbits(63))
        watermark_nonce = int(secrets.randbits(32))
        track_title = snapshot.track_title or f"Track {track_id}"
        suggested_name = sanitize_export_basename(f"{track_title} - authenticity")
        release_refs = self._build_release_refs(track_id)
        work_refs = self._build_work_refs(track_id)
        rights_summary = self._build_rights_summary(track_id, work_refs, release_refs)
        payload = {
            "authenticity_version": AUTHENTICITY_SCHEMA_VERSION,
            "watermark_version": WATERMARK_VERSION,
            "manifest_id": secrets.token_hex(16),
            "app_version": str(app_version),
            "created_at_utc": canonical_timestamp(),
            "track_ref": {
                "track_id": int(snapshot.track_id),
                "isrc": snapshot.isrc,
                "track_title": snapshot.track_title,
                "catalog_number": snapshot.catalog_number,
                "buma_work_number": snapshot.buma_work_number,
                "release_date": snapshot.release_date,
                "iswc": snapshot.iswc,
                "upc": snapshot.upc,
                "profile_name": profile_name,
            },
            "artist_ref": {
                "primary_artist_name": snapshot.artist_name,
            },
            "release_refs": release_refs,
            "work_refs": work_refs,
            "rights_summary": rights_summary,
            "reference_audio": {
                "source_kind": reference.source_kind,
                "source_track_id": int(track_id),
                "reference_asset_id": reference.reference_asset_id,
                "filename": reference.filename,
                "mime_type": reference.mime_type,
                "size_bytes": int(reference.size_bytes),
                "sha256": reference.sha256_hex,
                "sample_rate": reference.sample_rate,
                "bit_depth": reference.bit_depth,
                "format": reference.format_name,
            },
            "watermark_binding": {
                "watermark_id": watermark_id,
                "manifest_digest_prefix": "0" * 16,
                "watermark_nonce": watermark_nonce,
                "watermark_version": WATERMARK_VERSION,
            },
            "reference_fingerprint_b64": reference.fingerprint_b64,
            "signer": {
                "key_id": key_record.key_id,
                "signer_label": key_record.signer_label,
            },
        }
        payload["watermark_binding"]["manifest_digest_prefix"] = sha256_hex(
            manifest_bytes(payload)
        )[:16]
        canonical_bytes = manifest_bytes(payload)
        payload_sha256 = sha256_hex(canonical_bytes)
        signature_b64 = sign_bytes(private_key, canonical_bytes)
        token = WatermarkToken(
            version=WATERMARK_VERSION,
            watermark_id=watermark_id,
            manifest_digest_prefix=str(payload["watermark_binding"]["manifest_digest_prefix"]),
            nonce=watermark_nonce,
        )
        return PreparedAuthenticityManifest(
            track_id=int(track_id),
            track_title=track_title,
            suggested_name=suggested_name,
            key_id=key_record.key_id,
            signer_label=key_record.signer_label,
            public_key_b64=key_record.public_key_b64,
            payload=payload,
            payload_canonical=canonical_bytes.decode("utf-8"),
            payload_sha256=payload_sha256,
            signature_b64=signature_b64,
            watermark_token=token,
            reference=reference,
            embed_settings=watermark_settings_payload(),
        )

    def _decode_reference_audio(self, reference: ReferenceAudioSelection):
        import soundfile as sf

        if reference.source_bytes is None:
            if reference.source_path is None:
                raise ValueError("Reference audio is missing.")
            data, sample_rate = sf.read(str(reference.source_path), dtype="float32", always_2d=True)
        else:
            import io

            data, sample_rate = sf.read(
                io.BytesIO(reference.source_bytes), dtype="float32", always_2d=True
            )
        reference.sample_rate = reference.sample_rate or int(sample_rate)
        return data

    def _reference_sample_rate(self, reference: ReferenceAudioSelection) -> int:
        if reference.sample_rate is not None:
            return int(reference.sample_rate)
        self._decode_reference_audio(reference)
        return int(reference.sample_rate or 0)

    def save_manifest(
        self,
        prepared: PreparedAuthenticityManifest,
        *,
        embed_settings: dict[str, object] | None = None,
    ) -> AuthenticityManifestRecord:
        embed_json = canonical_text(embed_settings or prepared.embed_settings)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO AuthenticityManifests(
                    track_id,
                    reference_asset_id,
                    key_id,
                    manifest_schema_version,
                    watermark_version,
                    manifest_id,
                    watermark_id,
                    watermark_nonce,
                    manifest_digest_prefix,
                    payload_canonical,
                    payload_sha256,
                    signature_b64,
                    reference_audio_sha256,
                    reference_fingerprint_b64,
                    reference_source_kind,
                    embed_settings_json,
                    created_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), NULL)
                """,
                (
                    int(prepared.track_id),
                    prepared.reference.reference_asset_id,
                    prepared.key_id,
                    AUTHENTICITY_SCHEMA_VERSION,
                    WATERMARK_VERSION,
                    str(prepared.payload["manifest_id"]),
                    int(prepared.watermark_token.watermark_id),
                    int(prepared.watermark_token.nonce),
                    str(prepared.watermark_token.manifest_digest_prefix),
                    prepared.payload_canonical,
                    prepared.payload_sha256,
                    prepared.signature_b64,
                    prepared.reference.sha256_hex,
                    prepared.reference.fingerprint_b64,
                    prepared.reference.source_kind,
                    embed_json,
                ),
            )
        row = self.conn.execute(
            """
            SELECT
                id,
                track_id,
                reference_asset_id,
                key_id,
                manifest_schema_version,
                watermark_version,
                manifest_id,
                watermark_id,
                watermark_nonce,
                manifest_digest_prefix,
                payload_canonical,
                payload_sha256,
                signature_b64,
                reference_audio_sha256,
                reference_fingerprint_b64,
                reference_source_kind,
                embed_settings_json,
                created_at,
                revoked_at
            FROM AuthenticityManifests
            WHERE id=?
            """,
            (int(cursor.lastrowid),),
        ).fetchone()
        if row is None:
            raise RuntimeError("Manifest record was inserted but could not be reloaded.")
        return self._row_to_manifest(row)

    def _row_to_manifest(self, row) -> AuthenticityManifestRecord:
        return AuthenticityManifestRecord(
            id=int(row[0]),
            track_id=int(row[1]),
            reference_asset_id=int(row[2]) if row[2] is not None else None,
            key_id=str(row[3] or ""),
            manifest_schema_version=int(row[4] or 1),
            watermark_version=int(row[5] or 1),
            manifest_id=str(row[6] or ""),
            watermark_id=int(row[7] or 0),
            watermark_nonce=int(row[8] or 0),
            manifest_digest_prefix=str(row[9] or ""),
            payload_canonical=str(row[10] or ""),
            payload_sha256=str(row[11] or ""),
            signature_b64=str(row[12] or ""),
            reference_audio_sha256=str(row[13] or ""),
            reference_fingerprint_b64=str(row[14] or ""),
            reference_source_kind=str(row[15] or ""),
            embed_settings_json=_clean_text(row[16]),
            created_at=_clean_text(row[17]),
            revoked_at=_clean_text(row[18]),
        )

    def fetch_manifest_for_token(self, token: WatermarkToken) -> AuthenticityManifestRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                track_id,
                reference_asset_id,
                key_id,
                manifest_schema_version,
                watermark_version,
                manifest_id,
                watermark_id,
                watermark_nonce,
                manifest_digest_prefix,
                payload_canonical,
                payload_sha256,
                signature_b64,
                reference_audio_sha256,
                reference_fingerprint_b64,
                reference_source_kind,
                embed_settings_json,
                created_at,
                revoked_at
            FROM AuthenticityManifests
            WHERE watermark_id=?
              AND watermark_nonce=?
              AND manifest_digest_prefix=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                int(token.watermark_id),
                int(token.nonce),
                str(token.manifest_digest_prefix),
            ),
        ).fetchone()
        return self._row_to_manifest(row) if row else None

    def fetch_manifest_by_manifest_id(self, manifest_id: str) -> AuthenticityManifestRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                track_id,
                reference_asset_id,
                key_id,
                manifest_schema_version,
                watermark_version,
                manifest_id,
                watermark_id,
                watermark_nonce,
                manifest_digest_prefix,
                payload_canonical,
                payload_sha256,
                signature_b64,
                reference_audio_sha256,
                reference_fingerprint_b64,
                reference_source_kind,
                embed_settings_json,
                created_at,
                revoked_at
            FROM AuthenticityManifests
            WHERE manifest_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(manifest_id or ""),),
        ).fetchone()
        return self._row_to_manifest(row) if row else None

    def resolve_reference_for_payload(
        self,
        payload: dict[str, object],
    ) -> ReferenceAudioSelection | None:
        reference_audio = payload.get("reference_audio") or {}
        track_ref = payload.get("track_ref") or {}
        try:
            track_id = int(reference_audio.get("source_track_id") or track_ref.get("track_id") or 0)
        except Exception:
            track_id = 0
        source_kind = str(reference_audio.get("source_kind") or "").strip()
        if track_id <= 0 or not source_kind:
            return None
        try:
            if source_kind == "asset":
                asset_id = int(reference_audio.get("reference_asset_id") or 0)
                if asset_id > 0:
                    return self._reference_selection_from_asset(track_id, asset_id)
            if source_kind == "track_audio":
                return self._reference_selection_from_track_audio(track_id)
        except Exception:
            return None
        return None


class AudioWatermarkService:
    """Application-facing wrapper around the watermark core."""

    def __init__(self):
        self.core = AudioWatermarkCore()

    def settings_payload(self) -> dict[str, object]:
        return watermark_settings_payload()

    def embed_to_path(
        self,
        *,
        source_path: str | Path | None = None,
        source_bytes: bytes | None = None,
        destination_path: str | Path,
        watermark_key: bytes,
        token: WatermarkToken,
    ) -> dict[str, float | int]:
        return self.core.embed_to_path(
            source_path=source_path,
            source_bytes=source_bytes,
            destination_path=destination_path,
            watermark_key=watermark_key,
            token=token,
        )

    def extract_from_path(self, path: str | Path, *, watermark_keys: list[tuple[str, bytes]]):
        return self.core.extract_from_path(path, watermark_keys=watermark_keys)

    def verify_expected_token(
        self,
        path: str | Path,
        *,
        watermark_keys: list[tuple[str, bytes]],
        token: WatermarkToken,
    ):
        return self.core.verify_expected_token(
            path,
            watermark_keys=watermark_keys,
            token=token,
        )

    def verify_expected_token_against_reference(
        self,
        candidate_path: str | Path,
        *,
        reference_path: str | Path | None = None,
        reference_bytes: bytes | None = None,
        watermark_keys: list[tuple[str, bytes]],
        token: WatermarkToken,
    ):
        return self.core.verify_expected_token_against_reference(
            candidate_path,
            reference_path=reference_path,
            reference_bytes=reference_bytes,
            watermark_keys=watermark_keys,
            token=token,
        )


class AudioAuthenticityService:
    """Coordinates signed manifests, watermark embedding, exports, and verification."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        key_service: AuthenticityKeyService,
        manifest_service: AuthenticityManifestService,
        watermark_service: AudioWatermarkService,
        tag_service: AudioTagService,
        app_version: str,
    ):
        self.conn = conn
        self.key_service = key_service
        self.manifest_service = manifest_service
        self.watermark_service = watermark_service
        self.tag_service = tag_service
        self.app_version = app_version

    @staticmethod
    def _normalized_text(value: object | None) -> str:
        return str(value or "").strip().casefold()

    def _select_tag_release_context(
        self,
        *,
        track_id: int,
        snapshot_album_title: str | None,
    ) -> tuple[dict[str, object] | None, dict[str, object] | None, ArtworkPayload | None]:
        release_refs = self.manifest_service._build_release_refs(track_id)
        if not release_refs:
            return None, None, None

        chosen_ref: dict[str, object] | None = None
        if len(release_refs) == 1:
            chosen_ref = release_refs[0]
        else:
            clean_album_title = self._normalized_text(snapshot_album_title)
            if clean_album_title:
                matching_refs = [
                    ref
                    for ref in release_refs
                    if self._normalized_text(ref.get("title")) == clean_album_title
                ]
                if len(matching_refs) == 1:
                    chosen_ref = matching_refs[0]
        if chosen_ref is None:
            return None, None, None

        release_id = int(chosen_ref["release_id"])
        release = self.manifest_service.release_service.fetch_release(release_id)
        if release is None:
            return None, None, None

        placement_values = None
        for placement in self.manifest_service.release_service.list_release_tracks(release_id):
            if int(placement.track_id) != int(track_id):
                continue
            placement_values = {
                "track_number": int(placement.track_number),
                "disc_number": int(placement.disc_number),
            }
            break

        artwork = None
        if release.artwork_path or release.artwork_filename:
            try:
                artwork_bytes, mime_type = (
                    self.manifest_service.release_service.fetch_artwork_bytes(release_id)
                )
                artwork = ArtworkPayload(
                    data=artwork_bytes,
                    mime_type=str(mime_type or "image/jpeg"),
                    description=str(release.title or ""),
                )
            except Exception:
                artwork = None

        release_values = {
            "title": release.title,
            "primary_artist": release.primary_artist,
            "album_artist": release.album_artist,
            "release_date": release.release_date,
            "label": release.label,
            "upc": release.upc,
        }
        return release_values, placement_values, artwork

    def _build_export_tag_data(self, track_id: int):
        snapshot = self.manifest_service.track_service.fetch_track_snapshot(track_id)
        if snapshot is None:
            raise ValueError(f"Track {track_id} not found.")

        release_values, placement_values, artwork = self._select_tag_release_context(
            track_id=track_id,
            snapshot_album_title=snapshot.album_title,
        )
        return catalog_metadata_to_tags(
            track_values=asdict(snapshot),
            release_values=release_values,
            placement_values=placement_values,
            artwork=artwork,
        )

    def build_export_plan(
        self,
        track_ids: Iterable[int],
        *,
        key_id: str | None = None,
        profile_name: str | None = None,
    ) -> AuthenticityExportPlan:
        key_record = self.key_service.resolve_key(key_id)
        items: list[AuthenticityExportPlanItem] = []
        warnings: list[str] = []
        for raw_track_id in track_ids:
            try:
                track_id = int(raw_track_id)
            except Exception:
                continue
            snapshot = self.manifest_service.track_service.fetch_track_snapshot(track_id)
            if snapshot is None:
                warnings.append(f"Track {track_id} no longer exists and was skipped.")
                continue
            try:
                reference = self.manifest_service.select_reference_audio(track_id)
                items.append(
                    AuthenticityExportPlanItem(
                        track_id=track_id,
                        track_title=snapshot.track_title,
                        source_label=reference.source_label,
                        source_suffix=reference.suffix,
                        suggested_name=sanitize_export_basename(
                            f"{snapshot.track_title} - authenticity"
                        ),
                        key_id=key_record.key_id,
                    )
                )
            except Exception as exc:
                warning = f"{snapshot.track_title}: {exc}"
                warnings.append(warning)
                items.append(
                    AuthenticityExportPlanItem(
                        track_id=track_id,
                        track_title=snapshot.track_title,
                        source_label="Unsupported",
                        source_suffix="",
                        suggested_name=sanitize_export_basename(
                            f"{snapshot.track_title} - authenticity"
                        ),
                        key_id=key_record.key_id,
                        status="unsupported",
                        warning=str(exc),
                    )
                )
        return AuthenticityExportPlan(
            key_id=key_record.key_id,
            signer_label=key_record.signer_label,
            items=items,
            warnings=warnings,
        )

    def export_watermarked_audio(
        self,
        *,
        output_dir: str | Path,
        track_ids: Iterable[int],
        key_id: str | None = None,
        profile_name: str | None = None,
        progress_callback=None,
        is_cancelled=None,
    ) -> AuthenticityExportResult:
        plan = self.build_export_plan(track_ids, key_id=key_id, profile_name=profile_name)
        key_record, _private_key, watermark_key = self.key_service.signing_material(plan.key_id)
        destination_root = Path(output_dir)
        destination_root.mkdir(parents=True, exist_ok=True)
        exported = 0
        skipped = 0
        warnings = list(plan.warnings)
        written_audio_paths: list[str] = []
        written_sidecar_paths: list[str] = []
        manifest_ids: list[str] = []
        ready_items = plan.ready_items()
        total = len(ready_items)
        for index, item in enumerate(ready_items, start=1):
            if progress_callback is not None:
                progress_callback(
                    index - 1,
                    total,
                    f"Embedding authenticity watermark {index} of {total}: {item.track_title}",
                )
            if is_cancelled is not None and is_cancelled():
                raise InterruptedError("Authenticity export cancelled.")
            prepared = self.manifest_service.prepare_manifest(
                track_id=item.track_id,
                key_id=key_record.key_id,
                app_version=self.app_version,
                profile_name=profile_name,
            )
            destination = (destination_root / item.suggested_name).with_suffix(
                prepared.reference.suffix
            )
            try:
                tag_data = self._build_export_tag_data(item.track_id)
                embed_metrics = self.watermark_service.embed_to_path(
                    source_path=prepared.reference.source_path,
                    source_bytes=prepared.reference.source_bytes,
                    destination_path=destination,
                    watermark_key=watermark_key,
                    token=prepared.watermark_token,
                )
                self.tag_service.write_tags(destination, tag_data)
                stored_manifest = self.manifest_service.save_manifest(
                    prepared,
                    embed_settings={**prepared.embed_settings, **embed_metrics},
                )
                sidecar = build_sidecar_document(
                    schema_version=AUTHENTICITY_SCHEMA_VERSION,
                    payload=prepared.payload,
                    signature_b64=prepared.signature_b64,
                    public_key_b64=prepared.public_key_b64,
                    payload_sha256=prepared.payload_sha256,
                    key_id=prepared.key_id,
                )
                sidecar_path = destination.with_suffix(destination.suffix + ".authenticity.json")
                sidecar_path.write_text(
                    json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=True),
                    encoding="utf-8",
                )
                exported += 1
                written_audio_paths.append(str(destination))
                written_sidecar_paths.append(str(sidecar_path))
                manifest_ids.append(stored_manifest.manifest_id)
            except Exception as exc:
                skipped += 1
                warnings.append(f"{destination.name}: {exc}")
                destination.unlink(missing_ok=True)
                destination.with_suffix(destination.suffix + ".authenticity.json").unlink(
                    missing_ok=True
                )
        if progress_callback is not None:
            progress_callback(total, total, "Authenticity export finished.")
        skipped += max(0, len(plan.items) - len(ready_items))
        return AuthenticityExportResult(
            requested=len(plan.items),
            exported=exported,
            skipped=skipped,
            warnings=warnings,
            written_audio_paths=written_audio_paths,
            written_sidecar_paths=written_sidecar_paths,
            manifest_ids=manifest_ids,
        )

    def _load_adjacent_sidecar(self, inspected_path: Path) -> tuple[dict[str, object], Path] | None:
        candidates = [
            inspected_path.with_suffix(inspected_path.suffix + ".authenticity.json"),
            inspected_path.with_name(f"{inspected_path.stem}.authenticity.json"),
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8")), candidate
            except Exception:
                continue
        return None

    def verify_file(self, path: str | Path) -> AuthenticityVerificationReport:
        inspected_path = Path(path)
        if not inspected_path.exists() or not supported_audio_path(inspected_path):
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
                message="Verification currently supports existing WAV and FLAC files only.",
                inspected_path=str(inspected_path),
            )
        sidecar_payload = self._load_adjacent_sidecar(inspected_path)
        sidecar_doc: dict[str, object] | None = None
        sidecar_payload_dict: dict[str, object] | None = None
        sidecar_path_obj: Path | None = None
        sidecar_path_str: str | None = None
        sidecar_signature_valid = False
        sidecar_signature_b64 = ""
        sidecar_public_key_b64 = ""
        sidecar_payload_sha256 = ""
        sidecar_token: WatermarkToken | None = None
        if sidecar_payload is not None:
            sidecar_doc, sidecar_path_obj = sidecar_payload
            sidecar_path_str = str(sidecar_path_obj)
            payload_candidate = sidecar_doc.get("payload")
            if isinstance(payload_candidate, dict):
                sidecar_payload_dict = payload_candidate
                sidecar_signature_b64 = str(sidecar_doc.get("signature_b64") or "")
                sidecar_public_key_b64 = str(sidecar_doc.get("public_key_b64") or "")
                canonical = manifest_bytes(payload_candidate)
                sidecar_payload_sha256 = str(
                    sidecar_doc.get("payload_sha256") or sha256_hex(canonical)
                )
                if (
                    sidecar_signature_b64
                    and sidecar_public_key_b64
                    and sha256_hex(canonical) == sidecar_payload_sha256
                ):
                    try:
                        sidecar_signature_valid = verify_signature(
                            public_key_from_b64(sidecar_public_key_b64),
                            canonical,
                            sidecar_signature_b64,
                        )
                    except Exception:
                        sidecar_signature_valid = False
                binding = payload_candidate.get("watermark_binding") or {}
                try:
                    candidate_token = WatermarkToken(
                        version=int(binding.get("watermark_version") or WATERMARK_VERSION),
                        watermark_id=int(binding.get("watermark_id") or 0),
                        manifest_digest_prefix=str(binding.get("manifest_digest_prefix") or ""),
                        nonce=int(binding.get("watermark_nonce") or 0),
                    )
                except Exception:
                    candidate_token = None
                if (
                    candidate_token is not None
                    and candidate_token.watermark_id > 0
                    and len(candidate_token.manifest_digest_prefix) == 16
                ):
                    sidecar_token = candidate_token

        extraction_keys = self.key_service.extraction_keys()
        if not extraction_keys:
            details: list[str] = []
            if sidecar_signature_valid:
                details.append(
                    "Adjacent sidecar signature verified, but no local extraction key was available to test the keyed watermark binding."
                )
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
                message="No local extraction key is available for watermark detection.",
                inspected_path=str(inspected_path),
                sidecar_path=sidecar_path_str,
                details=details,
            )
        extraction = self.watermark_service.extract_from_path(
            inspected_path,
            watermark_keys=extraction_keys,
        )
        reference_guided_extraction = None
        sidecar_guided_extraction = None
        reference_selection = None
        if (
            (extraction.status != "detected" or extraction.token is None)
            and sidecar_signature_valid
            and sidecar_payload_dict is not None
            and sidecar_token is not None
        ):
            reference_selection = self.manifest_service.resolve_reference_for_payload(
                sidecar_payload_dict
            )
            if reference_selection is not None:
                reference_guided_extraction = (
                    self.watermark_service.verify_expected_token_against_reference(
                        inspected_path,
                        reference_path=reference_selection.source_path,
                        reference_bytes=reference_selection.source_bytes,
                        watermark_keys=extraction_keys,
                        token=sidecar_token,
                    )
                )
                if reference_guided_extraction.status == "detected":
                    extraction = reference_guided_extraction
            if extraction.status != "detected" or extraction.token is None:
                sidecar_guided_extraction = self.watermark_service.verify_expected_token(
                    inspected_path,
                    watermark_keys=extraction_keys,
                    token=sidecar_token,
                )
                if sidecar_guided_extraction.status == "detected":
                    extraction = sidecar_guided_extraction

        if extraction.status != "detected" or extraction.token is None:
            candidates = [
                candidate
                for candidate in (
                    reference_guided_extraction,
                    sidecar_guided_extraction,
                    extraction,
                )
                if candidate is not None
            ]
            active_result = max(
                candidates,
                key=lambda candidate: (
                    (
                        2
                        if candidate.status == "detected"
                        else 1 if candidate.status == "insufficient" else 0
                    ),
                    candidate.mean_confidence,
                    candidate.group_agreement,
                    candidate.sync_score,
                ),
            )
            if (
                reference_guided_extraction is not None
                and reference_guided_extraction.status == "none"
            ) or all(candidate.status == "none" for candidate in candidates):
                details = []
                no_watermark_result = (
                    reference_guided_extraction
                    if reference_guided_extraction is not None
                    and reference_guided_extraction.status == "none"
                    else active_result
                )
                if reference_guided_extraction is not None and reference_selection is not None:
                    details.append(
                        "Reference-aware keyed comparison against the stored source audio did not find the expected watermark energy."
                    )
                return AuthenticityVerificationReport(
                    status=VERIFICATION_STATUS_NO_WATERMARK,
                    message="No watermark was detected in the inspected audio.",
                    inspected_path=str(inspected_path),
                    key_id=no_watermark_result.key_id,
                    extraction_confidence=no_watermark_result.mean_confidence,
                    sidecar_path=sidecar_path_str,
                    details=details,
                )
            detail_lines = [
                f"sync_score={active_result.sync_score:.3f}",
                f"group_agreement={active_result.group_agreement:.3f}",
                f"repeat_groups={active_result.repeat_groups}",
            ]
            if reference_guided_extraction is not None and reference_selection is not None:
                detail_lines.append(
                    "Reference-aware keyed verification against the stored source audio stayed below the detection threshold."
                )
            elif sidecar_guided_extraction is not None:
                detail_lines.append(
                    "Adjacent sidecar signature verified, but direct keyed token recovery from the inspected audio stayed below the detection threshold."
                )
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
                message="A low-confidence watermark candidate was found, but it did not meet the verification threshold.",
                inspected_path=str(inspected_path),
                key_id=active_result.key_id,
                extraction_confidence=active_result.mean_confidence,
                sidecar_path=sidecar_path_str,
                details=detail_lines,
            )

        manifest_record = self.manifest_service.fetch_manifest_for_token(extraction.token)
        resolution_source = None
        payload: dict[str, object] | None = None
        signature_b64 = ""
        public_key_b64_value = ""
        payload_sha256 = ""
        reference_audio_sha256 = ""
        reference_fingerprint_b64 = ""
        key_id = extraction.key_id
        manifest_id = None
        if manifest_record is not None:
            resolution_source = "database"
            payload = json.loads(manifest_record.payload_canonical)
            signature_b64 = manifest_record.signature_b64
            key_record = self.key_service.fetch_key(manifest_record.key_id)
            public_key_b64_value = key_record.public_key_b64 if key_record is not None else ""
            payload_sha256 = manifest_record.payload_sha256
            reference_audio_sha256 = manifest_record.reference_audio_sha256
            reference_fingerprint_b64 = manifest_record.reference_fingerprint_b64
            key_id = manifest_record.key_id
            manifest_id = manifest_record.manifest_id
        elif (
            sidecar_signature_valid
            and sidecar_payload_dict is not None
            and sidecar_token is not None
            and int(sidecar_token.watermark_id) == int(extraction.token.watermark_id)
            and str(sidecar_token.manifest_digest_prefix)
            == str(extraction.token.manifest_digest_prefix)
            and int(sidecar_token.nonce) == int(extraction.token.nonce)
        ):
            resolution_source = "sidecar"
            payload = sidecar_payload_dict
            signature_b64 = sidecar_signature_b64
            public_key_b64_value = sidecar_public_key_b64
            payload_sha256 = sidecar_payload_sha256
            reference_audio = payload.get("reference_audio") or {}
            reference_audio_sha256 = str(reference_audio.get("sha256") or "")
            reference_fingerprint_b64 = str(payload.get("reference_fingerprint_b64") or "")
            signer = payload.get("signer") or {}
            key_id = str(signer.get("key_id") or key_id or "")
            manifest_id = str(payload.get("manifest_id") or "")
        if payload is None or not public_key_b64_value:
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
                message="A watermark was extracted, but no matching manifest could be resolved from the open profile or an adjacent sidecar.",
                inspected_path=str(inspected_path),
                key_id=key_id,
                watermark_id=extraction.token.watermark_id,
                extraction_confidence=extraction.mean_confidence,
            )

        canonical = manifest_bytes(payload)
        signature_valid = verify_signature(
            public_key_from_b64(public_key_b64_value),
            canonical,
            signature_b64,
        )
        if not signature_valid or sha256_hex(canonical) != str(
            payload_sha256 or sha256_hex(canonical)
        ):
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_SIGNATURE_INVALID,
                message="A watermark token was found, but the resolved manifest signature did not verify.",
                inspected_path=str(inspected_path),
                key_id=key_id,
                manifest_id=manifest_id,
                watermark_id=extraction.token.watermark_id,
                resolution_source=resolution_source,
                signature_valid=False,
                extraction_confidence=extraction.mean_confidence,
                sidecar_path=sidecar_path_str,
            )

        import soundfile as sf

        audio_data, sample_rate = sf.read(str(inspected_path), dtype="float32", always_2d=True)
        fingerprint_score = fingerprint_similarity(
            reference_fingerprint_b64, audio_data, int(sample_rate)
        )
        inspected_sha256 = sha256_hex(inspected_path.read_bytes())
        exact_hash_match = (
            bool(reference_audio_sha256) and inspected_sha256 == reference_audio_sha256
        )
        details = [
            f"signature_valid={signature_valid}",
            f"extraction_confidence={extraction.mean_confidence:.3f}",
            f"sync_score={extraction.sync_score:.3f}",
            f"group_agreement={extraction.group_agreement:.3f}",
            f"exact_hash_match={exact_hash_match}",
            f"fingerprint_similarity={fingerprint_score:.3f}",
        ]
        if fingerprint_score >= 0.92:
            return AuthenticityVerificationReport(
                status=VERIFICATION_STATUS_VERIFIED,
                message="Watermark extraction, manifest resolution, and Ed25519 signature verification all succeeded.",
                inspected_path=str(inspected_path),
                key_id=key_id,
                manifest_id=manifest_id,
                watermark_id=extraction.token.watermark_id,
                resolution_source=resolution_source,
                signature_valid=True,
                exact_hash_match=exact_hash_match,
                fingerprint_similarity=fingerprint_score,
                extraction_confidence=extraction.mean_confidence,
                sidecar_path=sidecar_path_str,
                details=details,
            )
        mismatch_note = (
            "The audio fingerprint similarity was below the strong-match threshold."
            if fingerprint_score < 0.85
            else "The audio fingerprint similarity was inconclusive for a strong match."
        )
        return AuthenticityVerificationReport(
            status=VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH,
            message=mismatch_note,
            inspected_path=str(inspected_path),
            key_id=key_id,
            manifest_id=manifest_id,
            watermark_id=extraction.token.watermark_id,
            resolution_source=resolution_source,
            signature_valid=True,
            exact_hash_match=exact_hash_match,
            fingerprint_similarity=fingerprint_score,
            extraction_confidence=extraction.mean_confidence,
            sidecar_path=sidecar_path_str,
            details=details,
        )

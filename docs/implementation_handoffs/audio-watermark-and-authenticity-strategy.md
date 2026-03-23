# Audio Watermark And Authenticity Strategy

## 1. Why Watermark Alone Was Not Considered Sufficient

This implementation does not treat watermarking as a standalone proof of ownership or authenticity.

- A watermark always changes the waveform slightly, so the real goal is perceptual transparency, not zero change.
- A watermark by itself is not a strong authenticity primitive. It can help link audio back to a catalog record, but it does not replace cryptographic signing.
- Version 1 is intentionally not DRM, not copy protection, and not a forensic-certainty claim.

For that reason, the shipped design is hybrid:

- a compact keyed watermark token is embedded into exported WAV or FLAC copies
- a deterministic manifest is signed with Ed25519
- verification reports only what the implementation can actually support

## 2. Final Hybrid Architecture

The implementation is split into four service layers under [`isrc_manager/authenticity`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity):

- `AuthenticityKeyService`: key generation, public-key registry rows, default-key selection, and local private-key file loading
- `AuthenticityManifestService`: reference-audio selection, signed payload construction, manifest persistence, and reference-audio resolution
- `AudioWatermarkService`: PCM watermark embedding plus keyed verification helpers
- `AudioAuthenticityService`: export planning, watermarked export, regular audio-tag writing for available catalog metadata, sidecar writing, and verification orchestration

The desktop integration points are:

- `Settings > Audio Authenticity Keys…`
- `Catalog > Export Authenticity Watermarked Audio…`
- `Catalog > Verify Audio Authenticity…`

The background service bundle also exposes the same services so export and verification can run off the UI thread with the repo’s existing task infrastructure.

## 3. Signed Manifest Format

The signed manifest is a deterministic JSON object serialized with:

```python
json.dumps(
    payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
).encode("utf-8")
```

The payload includes:

- `authenticity_version`
- `watermark_version`
- `manifest_id`
- `app_version`
- `created_at_utc`
- `track_ref`
- `artist_ref`
- `release_refs`
- `work_refs`
- `rights_summary`
- `reference_audio`
- `watermark_binding`
- `reference_fingerprint_b64`
- `signer`

The manifest is signed with Ed25519 using `cryptography.hazmat.primitives.asymmetric.ed25519`.

Verification-only mode is supported with the public key, but that verifies only the manifest signature. It does not magically prove the keyed watermark unless the app can also test the watermark path.

## 4. Embedded Token Format

The embedded watermark token is compact and redundancy-friendly. It does not contain the full manifest.

Token layout:

- `version`: 1 byte
- `watermark_id`: 8 bytes
- `manifest_digest_prefix`: 8 bytes
- `nonce`: 4 bytes
- `crc32`: 4 bytes

A fixed 16-bit sync word is prepended before payload bits are embedded.

The watermark binds audio back to the signed manifest through:

- `watermark_id`
- `manifest_digest_prefix`
- `watermark_nonce`
- `watermark_version`

## 5. Embedding And Extraction Method

### Audio scope

Version 1 is intentionally scoped to:

- WAV
- FLAC
- exported copies only

Original attached audio and original reference/master assets are left unchanged.

### STFT watermark

Embedding uses:

- `soundfile` for I/O
- `scipy.signal.stft` / `istft`
- Hann window
- `frame_length = 2048`
- `hop_length = 512`
- mid-band bins roughly between `1.5 kHz` and `5.5 kHz`
- keyed pseudorandom bin schedules
- repeated payload groups

Each bit uses a keyed chip pattern over 24 selected bins and a three-frame temporal pattern. The implementation preserves phase and perturbs magnitudes conservatively, with clipping to avoid large local changes.

### Practical verification model

There are two watermark-verification paths:

1. Blind keyed extraction from the inspected file alone
2. Reference-aware keyed verification against the original stored source audio

The blind extractor remains available, but in this repository the strongest and most reliable verification path is the reference-aware one. When the open profile still contains the original source audio referenced by the manifest, the app compares the inspected export against that stored source on the keyed STFT schedule. That sharply separates:

- true watermarked exports
- clean unwatermarked references

This is the most important practical choice in v1. It keeps the system technically honest instead of overstating portable blind-detection strength.

## 6. Verification Workflow

`AudioAuthenticityService.verify_file()` follows this sequence:

1. Reject unsupported files early unless they are WAV or FLAC.
2. Load any adjacent `*.authenticity.json` sidecar.
3. Verify the sidecar signature if enough data is present.
4. Attempt blind watermark extraction with local extraction keys.
5. If blind extraction is not strong enough and a valid sidecar plus open-profile reference audio are available, run reference-aware keyed verification against the stored source audio.
6. Resolve the manifest from:
   - the profile database by extracted token, or
   - a valid adjacent sidecar when the token matches
7. Verify the Ed25519 signature.
8. Compute:
   - exact SHA-256 equality against the stored reference audio hash
   - reference fingerprint similarity
9. Report exactly one result state:
   - `verified_authentic`
   - `watermark_found_signature_invalid`
   - `manifest_found_reference_mismatch`
   - `no_watermark_detected`
   - `unsupported_format_or_insufficient_confidence`

During authenticity export, the app also writes standard file metadata tags onto the exported WAV or FLAC copy. Track-level fields always come from the catalog snapshot, while release-level fields such as album title, album artist, UPC, label, disc number, and track number are only added when the linked release context is unambiguous enough to avoid mis-tagging alternate releases or compilations.

### Fingerprint thresholds

The coarse reference fingerprint is a signed 64-value float16 vector containing:

- 24 log-band means
- 24 log-band standard deviations
- 16 temporal-delta histogram values

Verification thresholds:

- `>= 0.92`: strong match
- `0.85` to `< 0.92`: insufficient for strong-match language
- `< 0.85`: mismatch

## 7. Key Management Model

Public keys are stored in the profile database table `AuthenticityKeys`.

Private keys are not stored in the profile database. They are written as PKCS8 PEM files under:

`settings_root()/keys/ed25519/<key_id>.pem`

The watermark extraction key is derived from the Ed25519 private key with HKDF-SHA256 using:

`b"isrcm-watermark-v1"`

Important limits:

- local private-key storage is explicit, practical, and documented
- it is not tamper-proof
- filesystem access to the private key is equivalent to signing authority for that local workflow

Version 1 does not attempt PKI, HSM, remote signing, or secret storage claims it cannot enforce.

## 8. Tests Added Or Updated

New tests:

- [`tests/test_authenticity_manifest_service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_authenticity_manifest_service.py)
- [`tests/test_audio_watermark_service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_audio_watermark_service.py)
- [`tests/test_authenticity_verification_service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_authenticity_verification_service.py)
- [`tests/database/test_schema_migrations_25_26.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/database/test_schema_migrations_25_26.py)
- [`tests/_authenticity_support.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/_authenticity_support.py)

Updated tests:

- [`tests/database/_schema_support.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/database/_schema_support.py)
- [`tests/test_background_app_services.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_background_app_services.py)
- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [`tests/app/test_app_shell_editor_surfaces.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_editor_surfaces.py)
- [`tests/test_help_content.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_help_content.py)
- [`tests/ci_groups.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/ci_groups.py)

The added coverage checks:

- deterministic manifest serialization
- Ed25519 sign/verify round-trip
- manifest persistence
- WAV and FLAC watermark embedding
- bounded waveform deltas
- short-audio failure behavior
- reference-aware token recovery from clean exports
- all main verification result states
- schema migration to v26
- background service bundle availability
- app-shell action exposure

## 9. Known Limitations

These limits should remain explicit in product language and future code review:

- This is not DRM.
- This is not copy protection.
- This does not claim forensic certainty.
- Watermarking is perceptually transparent, not waveform-identical.
- Version 1 is WAV/FLAC-first. MP3/AAC/OGG/Opus workflows are out of scope for embedding and strong verification.
- The strongest keyed verification depends on the open profile still having the original reference audio available.
- Sidecar-only verification can prove the manifest signature, but without a local extraction key and reference audio it may not be able to prove the watermark binding strongly enough.
- Robustness claims should stay limited to same-program export/reload, trivial rewrites, and modest non-adversarial handling.
- Local private-key storage is only best-effort protected by filesystem permissions.

## 10. Future Roadmap

The most useful next steps would be:

- stronger blind extraction for sidecar-only verification
- optional forward-error-correction around the compact token
- codec- and transcode-tolerance evaluation before making any robustness claims beyond PCM workflows
- reference-audio caching or derived verification artifacts for faster repeated verification
- remote or delegated signing support for teams that do not want private keys on workstation disks
- clearer operator UX around “signature valid but keyed watermark insufficient” versus “reference mismatch”

## Implementation Notes

Relevant implementation files:

- [`isrc_manager/authenticity/crypto.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/crypto.py)
- [`isrc_manager/authenticity/manifest.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/manifest.py)
- [`isrc_manager/authenticity/models.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/models.py)
- [`isrc_manager/authenticity/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/service.py)
- [`isrc_manager/authenticity/watermark.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/authenticity/watermark.py)
- [`isrc_manager/help_content.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/help_content.py)
- [`isrc_manager/services/schema.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/services/schema.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)

# Forensic Watermarking Export Ledger

## 1. How Forensic Watermarking Differs From Authenticity Watermarking

This pass adds a separate forensic watermark workflow for recipient-specific delivery copies.

Authenticity watermarking remains the canonical master workflow:
- intended for authenticity-safe master exports
- tied to signed authenticity manifests and Ed25519-backed authenticity records
- verified through the existing authenticity verification flow

Forensic watermarking is different:
- intended for leak tracing and export attribution
- recipient- and export-specific
- tied to the derivative/export ledger instead of the signed authenticity manifest model
- does not claim perfect adversarial resistance
- does not claim the same authenticity basis as the signed-master workflow

The two systems intentionally share some low-level building blocks, but they remain separate at the payload, ledger, UI, and verification layers.

## 2. What The Previous Pipeline Supported

Before this pass, the repo already supported:
- lossy primary-file awareness
- managed derivative export with metadata embedding
- watermark-authentic managed exports
- provenance-only lossy authenticity exports
- derivative ledger tracking
- external file-picker conversion
- background task/progress execution

What was missing was recipient-specific forensic watermarking layered onto the managed export/derivative system.

## 3. Export-Ledger Model

This implementation builds on the existing managed derivative ledger instead of creating an unrelated tracker.

Existing reused ledger spine:
- `DerivativeExportBatches`
- `TrackAudioDerivatives`

New forensic table:
- `ForensicWatermarkExports`

Each forensic export now records:
- `forensic_export_id`
- `batch_id`
- `derivative_export_id`
- `track_id`
- `key_id`
- `token_version`
- `forensic_watermark_version`
- `token_id`
- `binding_crc32`
- `recipient_label`
- `share_label`
- `output_format`
- `output_filename`
- `output_sha256`
- `output_size_bytes`
- `source_lineage_ref`
- `created_at`
- `last_verified_at`
- `last_verification_status`
- `last_verification_confidence`

The derivative ledger remains reference-only. No exported forensic audio is stored in SQLite.

## 4. Payload / Token Design

The forensic watermark uses a compact token designed for ledger resolution rather than large embedded metadata.

Current token layout:
- `version`: 1 byte
- `token_id`: 6 bytes / 48-bit integer
- `binding_crc32`: 4 bytes
- `crc32`: 4 bytes

Total payload size:
- 15 bytes

`binding_crc32` is derived from batch/export binding inputs:
- batch id
- track id
- output format
- recipient label
- share label

The richer mapping stays in the database. The watermark payload itself remains compact and resolvable.

## 5. Reused Vs Separate Components

Reused from the authenticity stack:
- Ed25519 key ownership and local private-key loading through `AuthenticityKeyService`
- low-level STFT watermark DSP shape and supporting FFT/bin/frame helpers
- managed source resolution through `TrackService.resolve_media_source()`
- catalog tag-building via `build_catalog_tag_data(...)`
- managed derivative batch/item ledger
- background task/progress infrastructure

Kept separate for forensic behavior:
- forensic token format
- forensic key derivation namespace
- forensic watermark service/core
- forensic export ledger table
- forensic inspection statuses and reporting
- forensic export dialog and inspection dialog
- product wording and menu actions

The forensic key derivation uses a separate HKDF info label:
- authenticity: `isrcm-watermark-v1`
- forensic: `isrcm-forensic-watermark-v1`

## 6. Supported Forensic Target Formats

Honest v1 direct forensic watermark embedding is limited to:
- `WAV`
- `FLAC`
- `AIFF`

Why:
- the current embedding/detection core is still PCM/lossless oriented
- local investigation did not justify claiming robust lossy forensic support yet
- the implementation avoids overstating leak-tracing strength on lossy re-encodes

The architecture is prepared for future lossy forensic support, but v1 only exports direct forensic watermarks to the lossless/authenticity-safe set above.

## 7. Forensic Export Workflow

UI entry points:
- `Catalog > Export Forensic Watermarked Audio…`
- catalog table context menu equivalent
- action ribbon id `forensic_export_audio`

Workflow steps:
1. resolve source from managed-file or blob-backed catalog audio
2. convert to selected forensic-supported target
3. write catalog metadata
4. embed recipient/export-specific forensic watermark
5. hash the completed output file
6. create derivative ledger row
7. create forensic export ledger row
8. finalize filename with short hash suffix
9. ZIP package if bulk

Per exported file:
- one unique derivative export id
- one unique forensic export id
- one unique forensic token id

Batch behavior:
- bulk forensic exports share one batch id
- each file still gets its own forensic export id and token
- bulk outputs are packaged as `forensic-export-<batch_id>.zip`

## 8. Detection / Resolution Workflow

UI entry points:
- `Catalog > Inspect Forensic Watermark…`
- `File > Inspect Forensic Watermark…`
- catalog table context menu equivalent
- action ribbon id `forensic_inspect_audio`

Inspection flow:
1. choose a file
2. attempt direct forensic token extraction
3. resolve extracted token against `ForensicWatermarkExports`
4. if unresolved, check exact output-hash match against the ledger
5. if still unresolved, run reference-guided comparison against known forensic exports by rebuilding the expected unwatermarked reference from current catalog source audio
6. return the strongest technically honest result

Current result states:
- `forensic_match_found`
- `forensic_match_low_confidence`
- `forensic_watermark_not_detected`
- `unsupported_format_or_insufficient_confidence`
- `token_found_but_unresolved`

Important note:
- blind extraction on the current DSP path is conservative and may not always be the strongest detection path
- the reference-guided comparison fallback is what makes v1 useful without overclaiming blind robustness

## 9. UI / Product Messaging Changes

Added explicit forensic wording rather than folding this into authenticity export:
- `Export Forensic Watermarked Audio…`
- `Inspect Forensic Watermark…`

The UI messaging distinguishes:
- direct authenticity master exports
- provenance-linked authenticity lossy copies
- managed derivatives
- forensic leak-tracing copies
- external conversion utility outputs

Forensic export copy text emphasizes:
- recipient-specific leak tracing
- catalog metadata still written
- derivative and forensic ledger registration
- not the same as direct authenticity verification

## 10. Tests Added / Updated

New tests:
- `tests/test_forensic_watermark_service.py`
- `tests/database/test_schema_migrations_28_29.py`

Updated tests:
- `tests/_authenticity_support.py`
- `tests/test_background_app_services.py`
- `tests/app/_app_shell_support.py`
- `tests/database/_schema_support.py`
- `tests/ci_groups.py`

Validated behaviors include:
- single forensic export
- bulk forensic export with unique ids
- metadata writing on forensic exports
- final hash after forensic watermarking
- derivative/export ledger linkage
- ZIP packaging for bulk forensic exports
- inspection resolving a known export
- unresolved token status
- low-confidence path
- unsupported/not-detected path
- schema v28 -> v29 migration
- background service bundle exposure
- app action/menu/context/ribbon surfaces
- no regression in existing managed derivative or authenticity verification slices

## 11. Current Robustness Limits

Current limits must remain explicit:
- this is not DRM
- this is not perfect leak attribution
- this does not claim robustness against deliberate stripping, severe editing, or repeated hostile transcoding
- v1 does not honestly claim direct lossy forensic watermark support yet
- direct blind token extraction is conservative; reference-guided matching is often the stronger path
- inspection depends on the open profile containing the relevant export ledger and local key material
- reference-guided recovery is strongest when the current catalog source audio still matches the stored source SHA-256

## 12. Future Roadmap For Stronger Lossy Forensic Support

The architecture leaves room for a stronger lossy forensic branch later:
- separate forensic token versions
- format-specific embed/detect tuning for practical lossy delivery formats
- recipient-party linkage if lightweight party reuse becomes desirable
- dedicated forensic resolution event history
- better batch/member-path ledger enrichment
- stronger blind extraction and re-encode robustness testing
- explicit recipient-specific lossy delivery presets

The current design keeps those future additions possible without conflating them with the signed authenticity workflow.

# Managed Lossy Audio Export Follow-Up

This handoff documents the follow-up pass that closes the remaining feature gap in the managed audio conversion system: catalog-managed exports can now produce lossy derivatives where the local runtime can honestly support them.

## 1. What The Previous Pipeline Supported

The first pass delivered:

- lossy primary-file warnings and catalog visual distinction
- one managed derivative coordinator for catalog-owned audio
- metadata embedding from the catalog database
- watermark injection for watermark-safe managed outputs
- final hashing and derivative-ledger tracking
- ZIP packaging for bulk managed exports
- a separate external file-picker conversion utility

The gap was that the managed branch only exposed watermark-safe `WAV`, `FLAC`, and `AIFF` outputs.

## 2. What Feature Gap Was Closed Here

Managed catalog exports now support two explicit result classes inside the same managed derivative-export system:

1. `Watermark-authentic managed derivatives`
   - lossless / watermark-safe targets
   - convert
   - embed DB metadata
   - apply direct watermark
   - hash after watermark
   - register derivative lineage

2. `Managed lossy derivatives`
   - runtime-supported lossy targets
   - convert
   - embed DB metadata
   - skip direct watermark when the current watermark stack is not honest for that target
   - hash the completed output file
   - register derivative lineage

The external utility path stays separate and never writes metadata, watermarks, or ledger rows.

## 3. How Managed Lossy Export Now Works

The central coordinator is still `ManagedDerivativeExportCoordinator`.

For lossy managed exports, the implemented order is:

1. resolve catalog-managed source audio through `TrackService.resolve_media_source()`
2. convert with `AudioConversionService`
3. write database metadata with `build_catalog_tag_data(..., release_policy="unambiguous")`
4. explicitly skip direct watermarking for lossy targets
5. compute the final SHA-256 on the completed exported file
6. create the derivative ledger row
7. finalize the filename with the short hash suffix
8. ZIP package the batch if more than one item was exported

The source attachment is never mutated in place.

## 4. How It Differs From Watermark-Authentic Managed Export

The managed export UI now makes the branch semantics explicit by target class:

- `WAV`, `FLAC`, and `AIFF` remain on the watermark-authentic path
- lossy targets become managed derivatives with metadata and lineage, but without a direct authenticity watermark

Ledger semantics distinguish them with:

- `workflow_kind = managed_audio_derivative`
- `derivative_kind = watermark_authentic` or `lossy_derivative`
- `authenticity_basis = direct_watermark` or `catalog_lineage_only`
- `watermark_applied = 1` or `0`

This keeps direct watermark authenticity separate from derivative/provenance-only lineage.

## 5. Runtime Format-Capability Gating

`AudioConversionService` now reports three capability slices:

- `managed_targets`
  - current watermark-authentic managed targets
  - currently `wav`, `flac`, `aiff`
- `managed_lossy_targets`
  - runtime-probed lossy managed targets that pass the full encoder/container/tagging path
  - currently probed from `mp3`, `ogg`, `opus`, `m4a`
- `external_targets`
  - broader runtime-supported utility targets
  - may include raw `aac` if ffmpeg can encode it

Managed lossy targets are not exposed just because ffmpeg lists an encoder. Each candidate must also survive metadata writing and metadata read-back. Raw `.aac` is intentionally excluded from managed lossy exports because the current tag layer is not honest there; use `.m4a` instead.

## 6. Derivative Ledger Changes

The schema target is now `28`.

`DerivativeExportBatches` now records:

- `workflow_kind`
- `derivative_kind`
- `authenticity_basis`

`TrackAudioDerivatives` now records:

- `workflow_kind`
- `derivative_kind`
- `authenticity_basis`
- `watermark_applied`
- `metadata_embedded`
- `output_sha256`
- `filename_hash_suffix`
- `source_lineage_ref`
- `source_storage_mode`

The ledger remains reference-only. No derivative file bytes are stored in SQLite.

## 7. UI / Menu / Context-Menu Changes

The managed export entry remains a single explicit managed-derivative action:

- `Export Managed Audio Derivatives…`

Supporting wording now explains:

- lossless targets stay on the watermark-authentic path
- lossy targets export as tagged managed derivatives with derivative lineage
- the external utility remains separate and does not use catalog metadata or derivative registration

Related actions are now named more clearly:

- `Export Managed Audio Derivatives…`
- `Export Watermark-Authentic Masters…`
- `Export Provenance-Linked Lossy Copies…`
- `External Audio Conversion Utility…`

The catalog context menu mirrors the same wording.

## 8. Tests Added / Updated

Added or updated coverage includes:

- managed single-track lossy export
- managed bulk lossy export
- managed lossy export from blob-backed source
- managed-file and blob-backed source preservation
- metadata embedding on managed lossy exports
- final hash on the completed lossy file
- derivative rows distinguishing watermark-authentic vs lossy managed exports
- ZIP packaging for managed lossy bulk export
- capability gating for lossy managed targets and external targets
- no regression in watermark-authentic managed export
- no regression in external utility conversion
- schema migration coverage for `27 -> 28`
- app-shell wording and context-menu exposure

Relevant files:

- `tests/test_audio_conversion_pipeline.py`
- `tests/database/test_schema_migrations_27_28.py`
- `tests/app/_app_shell_support.py`

## 9. Future Forensic Watermark Compatibility

The lossy managed branch was deliberately kept as `catalog_lineage_only`, not as a fake watermark-authentic workflow.

That keeps room for a later forensic extension such as:

- recipient-specific lossy watermark embedding
- a separate forensic watermark stage after metadata writing
- additional ledger fields describing recipient, watermark method, or forensic token lineage

Because the ledger already stores stable `source_lineage_ref`, `batch_id`, `export_id`, and final output hashes, a future forensic lossy workflow can layer on without breaking the current direct-watermark model.

## 10. Remaining Limitations

- Direct authenticity watermarking still applies only to the current watermark-safe managed target set.
- Managed lossy targets are limited to formats that pass both conversion and metadata round-trip checks at runtime.
- Raw `.aac` remains external-only for now.
- The managed derivative UI is one clearly worded flow, not two separate actions. The branch is determined by the chosen output target class.

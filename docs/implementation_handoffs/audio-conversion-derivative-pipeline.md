# Audio Conversion + Derivative Tracking Pipeline

This handoff describes the implemented controlled audio conversion/export work across the catalog UI, conversion backend, authenticity services, and the derivative ledger.

## Workflow Split

The application now exposes three related workflows that share scaffolding but stay behaviorally separate:

1. `Lossy primary import awareness`
   - The user may attach lossy audio as the primary track file.
   - The attach/edit flows warn at pick-time and at commit-time.
   - Catalog rows with lossy primary audio render with a separate themed badge/icon state.

2. `Managed-catalog derivative conversion/export`
   - Starts from selected catalog tracks with attached primary audio.
   - Resolves managed-file and blob-backed sources through one shared `TrackService.resolve_media_source()` seam.
   - Converts into a managed derivative target, writes DB metadata, applies watermarking, hashes the watermarked output, records a derivative ledger row, adds a readable hash suffix, and ZIP-packages bulk batches.
   - Never replaces the source attachment and never stores derivative file bytes in SQLite.

3. `External file-picker conversion utility`
   - Starts from arbitrary user-picked files outside the catalog.
   - Reuses only conversion, staging, and ZIP naming helpers.
   - Does not write DB metadata, does not watermark, and does not create derivative ledger rows.

## Lossy Primary-File Policy

- Lossy/lossless state is derived from the canonical audio format registry, using suffix and MIME data.
- Lossy primary attachments are allowed for `.mp3`, `.ogg/.oga`, `.opus`, `.m4a/.mp4`, and `.aac`.
- Add-track, edit-track, and bulk-attach surfaces show a clear warning before the attachment is committed.
- The catalog `Audio File` cell now distinguishes lossy primary audio with the `audio_lossy` blob icon slot and a tooltip such as `Lossy primary audio · MP3`.
- The lossy icon is editable from the existing Blob Icons theme/settings surface alongside the standard `audio` and `image` icons.

## Managed-Catalog Derivative Pipeline

The managed export coordinator is `ManagedDerivativeExportCoordinator`. It is the only path that creates derivative ledger rows.

Implemented order of operations:

1. Resolve the source track audio from managed storage or blob storage through `TrackService.resolve_media_source()`.
2. Convert the source with `AudioConversionService`.
3. Build DB-backed tag payloads through `build_catalog_tag_data(..., release_policy="unambiguous")`.
4. Write metadata into the converted output.
5. Apply watermarking through `AudioAuthenticityService.watermark_catalog_derivative()`.
6. Compute the final SHA-256 from the already-watermarked output.
7. Create the derivative ledger row and reserve the final hash-suffixed filename.
8. Move the finalized derivative into place, or package the batch into a ZIP for bulk exports.

Important rule:

- Hashing happens after watermarking. The recorded hash and the filename suffix must always describe the final post-watermark bytes.

Managed source support:

- Attached managed-file track audio
- Attached blob-backed track audio

Managed output targets in v1:

- `WAV`
- `FLAC`
- `AIFF`

Those are the only managed targets because the watermarking subsystem is intentionally limited to direct watermark-capable PCM/lossless containers.

## External Conversion Utility Path

The external conversion coordinator is `ExternalAudioConversionCoordinator`.

- Inputs come from a file picker, not from selected catalog rows.
- The workflow converts one or more files into the requested target format.
- Multi-file exports are ZIP-packaged with the shared batch naming helper.
- No DB metadata is embedded.
- No watermark is applied.
- No derivative ledger or authenticity manifest rows are created.

The external workflow is feature-gated on `ffmpeg` availability. If `ffmpeg` is missing, the action is disabled and the user receives an explicit message.

## Derivative Ledger Model

The schema target is now `27`.

`DerivativeExportBatches` stores per-run identity and packaging state:

- `batch_id`
- `workflow_kind`
- `package_mode`
- `output_format`
- `zip_filename`
- `recipe_canonical`
- `recipe_sha256`
- `requested_count`
- `exported_count`
- `skipped_count`
- `created_at`
- `completed_at`
- `status`

`TrackAudioDerivatives` stores per-output identity and lineage:

- `export_id`
- `batch_id`
- `track_id`
- `source_kind`
- `source_lineage_ref`
- `source_audio_sha256`
- `source_storage_mode`
- `derivative_manifest_id`
- `output_format`
- `output_suffix`
- `output_filename`
- `filename_hash_suffix`
- `watermark_applied`
- `metadata_embedded`
- `output_sha256`
- `output_size_bytes`
- `package_member_path`
- `status`
- `created_at`
- `updated_at`

The ledger is reference-only:

- derivative files are written to disk
- SQLite stores hashes, filenames, batch ids, and lineage only
- no derivative blobs are stored

## Hash Suffixes And ZIP Behavior

- Final filenames use `<base>--<first12hex>.<ext>`.
- The full final SHA-256 is stored in the ledger.
- Single managed exports write the finalized derivative directly to the chosen destination folder.
- Bulk managed exports write finalized derivatives into a temp batch directory and then package them into `audio-export-<batch_id>.zip`.
- The batch row records `package_mode` and `zip_filename`.
- External multi-file conversions use the same ZIP naming pattern, but no DB batch row is written.

## Watermark Integration Point

`AudioAuthenticityService.watermark_catalog_derivative()` is the managed-only watermark hook.

- It prepares an authenticity manifest for the converted pre-watermark file.
- It reads the already-written tags from that file.
- It runs the watermark embed step into a new output path.
- It rewrites the preserved tags onto the watermarked output as part of the watermark stage.
- It persists the authenticity manifest and returns its identifier for derivative linkage.

This keeps metadata logically ahead of final hashing while preserving the already-written tags on the watermarked file.

## Tests Added Or Updated

Added:

- `tests/test_audio_conversion_pipeline.py`

Updated:

- `tests/app/_app_shell_support.py`
- `tests/test_blob_icons.py`
- `tests/test_tag_dialogs.py`
- `tests/test_theme_builder.py`
- `tests/database/_schema_support.py`

Covered scenarios include:

- lossy warning and catalog badge behavior
- theme-configurable lossy icon support
- managed export from managed-file sources
- managed export from blob-backed sources
- mixed-source bulk managed export with ZIP packaging
- metadata embedding on managed exports
- watermark application on managed exports
- final-hash-after-watermark ordering
- derivative ledger writes without derivative blobs
- readable filename hash suffixes
- external conversion without metadata, watermarking, or ledger registration
- no mutation of original source audio
- regression coverage for existing authenticity and tag-writing flows

## Current Limits And Follow-Up Notes

- Managed exports require both `ffmpeg` and the existing authenticity stack.
- External target formats beyond the baseline are runtime-probed and should not be promised unless the installed encoder is available.
- The derivative ledger intentionally stores references only; it does not supersede `AssetVersions` or the history system.
- Future forensic watermarking can layer on top of the current ledger by reusing `batch_id`, `export_id`, `source_lineage_ref`, and `derivative_manifest_id` without changing the current direct-watermark verification model.

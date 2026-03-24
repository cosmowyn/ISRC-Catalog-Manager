# Import and Merge Workflows

This guide documents the current import surfaces in ISRC Catalog Manager as they exist today.

The product has three distinct ingest paths:

- exchange import for structured catalog rows
- XML import for supported XML exchange files
- audio tag import for embedded metadata round-tripping, plus export-time metadata embedding on catalog-backed audio workflows

The workflows overlap in the data they can touch, but they are not the same feature. Each path has different match rules, write behavior, and limits.

## Exchange Import

Exchange import is the tabular and package-based workflow used for bringing structured catalog data into the database.

### Supported Input Types

- `CSV`
- `XLSX`
- `JSON`
- `ZIP package`

### What The Exchange Workflow Can Target

The import target list includes the standard catalog and release fields used by the exchange layer, plus active non-blob custom text fields exposed as `custom::<name>`.

Examples of supported target families include:

- track identity and descriptive metadata such as `track_id`, `isrc`, `track_title`, `artist_name`, `additional_artists`, `album_title`, `release_date`, `track_length_sec`, `track_length_hms`, `iswc`, `upc`, `genre`, `catalog_number`, `buma_work_number`, `composer`, `publisher`, `comments`, and `lyrics`
- file-backed fields such as `audio_file_path`, `audio_file_storage_mode`, `album_art_path`, `album_art_storage_mode`
- release-level fields such as `release_id`, `release_title`, `release_version_subtitle`, `release_primary_artist`, `release_album_artist`, `release_type`, `release_date_release`, `release_original_release_date`, `release_label`, `release_sublabel`, `release_catalog_number`, `release_upc`, `release_barcode_validation_status`, `release_territory`, `release_explicit_flag`, `release_notes`, `release_artwork_path`, and `release_artwork_storage_mode`
- placement fields such as `disc_number`, `track_number`, and `sequence_number`
- `license_files`
- active text custom fields such as `custom::publisher_share`, `custom::territory_notes`, or any other existing active custom text field name

Blob custom fields are not tabular import targets in this workflow.

### CSV Delimiter Behavior

CSV import supports the delimiter controls exposed by the setup dialog.

- Auto-detect recognizes comma, semicolon, tab, and pipe
- A custom delimiter must be exactly one non-newline character
- The selected delimiter is applied to both inspection and import

This matters for real-world exports because the same catalog file may arrive as comma-separated, semicolon-separated, or tab-separated data depending on the source system or region.

### Mapping Presets, Skip Targets, And Field Mapping

CSV and XLSX are still the most visible mapping workflows because they begin from arbitrary source columns, but the same exchange setup surface now also governs JSON and ZIP package imports.

- Mapping presets can be saved and reused
- Source columns can be mapped to standard fields or active `custom::<name>` text fields
- Missing text custom fields can be created during setup when you want the import to introduce those targets instead of requiring a separate pre-creation pass
- Any source field can be marked as `Skip this field` when you want it inspected but not applied
- The mapping layer is not intended for blob fields
- JSON and ZIP package imports now use the same mode, match-rule, target-resolution, and skip behavior as the spreadsheet imports, even though their source structure is already defined by the payload or package manifest

### Saved Import Choices

The exchange dialog can remember setup choices per format.

- `Remember these ... import choices` stores the current mode, match options, custom-field creation preference, and CSV delimiter settings for that specific format
- `File > Import Exchange > Reset Saved Import Choices…` clears those persisted choices when you want to start fresh
- This is especially useful when one source family is usually merged with heuristics while another is usually create-only or validation-first

This is what makes the workflow useful for structured exports from labels, catalog systems, publishers, distributors, and PRO-style export files. If a system can export to a supported format, its fields can be mapped into the catalog without a custom integration.

Examples of source systems that can fit this pattern include BUMA, STEMRA, SENA, and similar metadata or reporting sources, provided the file is exported into one of the supported formats.

### Import Modes

Exchange import supports these modes:

- `dry_run`
- `create`
- `update`
- `merge`
- `insert_new`

Their behavior is different:

- `dry_run` performs a preflight import pass and writes nothing to the database
- `create` always creates new tracks
- `update` updates only matched rows and skips unmatched rows
- `merge` updates matched rows while preserving existing populated values for many core fields
- `insert_new` creates only when no match exists and skips matched rows as duplicates

The dry-run mode is useful for checking setup, mapping, and match behavior before committing changes. It is not a full semantic validation of every row.

### Match Precedence

When the importer looks for an existing track, it follows a fixed precedence:

1. internal `track_id`, if matching by internal ID is enabled
2. ISRC, if matching by ISRC is enabled
3. UPC plus title, if that match option is enabled
4. case-insensitive exact title plus artist, if heuristic matching is enabled
5. for `merge` mode only, a unique case-insensitive exact title plus artist fallback can still resolve the row even when heuristic matching is off

That precedence is important because it explains why some imports update an existing row while others create a new one. The importer is deterministic; it does not expose a manual row-by-row assignment queue.

### Merge Behavior

`merge` is not a simple overwrite mode.

When a row matches an existing track, merge preserves many existing populated values on the catalog side instead of blindly replacing them. The implementation protects fields such as:

- track title
- artist
- album title
- release date
- track length
- ISWC
- UPC
- genre
- catalog number
- BUMA work number
- composer
- publisher
- comments
- lyrics

If the source row provides a new media path, that path can still be applied. If the source row does not provide one, the existing media reference is kept.

This makes merge useful for bringing in supplemental metadata from a source export without discarding values that are already curated in the catalog. It is still a rule-based merge, not a field-by-field human reconciliation screen, so not every field has the same preservation behavior.

### Release Upsert Behavior

Release data is upserted as part of the exchange workflow after the track row is processed.

The release matcher checks in this order:

1. `release_id`
2. `release_upc`
3. `release_title` plus `release_catalog_number`

If a release is found, it can be updated from the supplied release-row data. If no matching release exists, a new release is created and linked to the track.

This is not a fill-blanks-only workflow. Release-level data can be updated or overwritten from the import source when the row matches a release.

### Media Paths, Packages, And Storage-Mode Round-Tripping

The exchange workflow can carry file references alongside catalog data.

- Relative file paths are resolved against the source file directory during import
- Package imports extract bundled contents to a safe temporary location before import
- ZIP package imports can round-trip packaged media and preserve the storage mode recorded in the package manifest
- File-backed rows can therefore remain database-backed or managed-file-backed after a package round trip, instead of being flattened into one representation

This is one of the reasons the package workflow is useful for moving a complete working set between systems or machines.

### Practical Workflow Examples

- Import a CSV export from a catalog administrator, map the source title and contributor columns to `track_title`, `artist_name`, and `composer`, then use `merge` to bring the new data into rows that already exist in the catalog.
- Import a label or PRO-style spreadsheet export, map its work reference column to `buma_work_number`, and map any local reporting columns to active `custom::<name>` fields.
- Import a ZIP package that contains catalog rows plus bundled media, then use the package round trip to restore both the metadata and the packaged files in one pass.

## Bulk Attach Audio Files

Bulk audio attachment is a separate catalog workflow rather than a row-oriented exchange import.

- Open `Catalog > Bulk Attach Audio Files…` when the track rows already exist and the remaining job is to connect audio files to them
- The workflow inspects filenames and embedded tags, suggests likely track matches, and lets you reassign or skip files before anything is written
- You can choose whether the attached audio should be stored in the database or as managed local files
- One optional artist value can be applied across the matched set when you are cleaning up a consistent batch
- The final apply step is recorded as one recoverable history mutation instead of as a series of isolated row edits

## XML Import

XML import is a separate service with separate semantics.

### Supported XML Shapes

The importer recognizes two supported document shapes:

- `DeclarationOfSoundRecordingRightsClaimMessage` with `SoundRecording` entries
- `Tracks` with nested `Track` entries

If the root element does not match one of those shapes, the file is rejected.

### What XML Import Does

XML import is insert-oriented.

- It creates new tracks for valid, non-duplicate records
- It does not offer update or merge semantics
- It does not offer manual row assignment

This makes XML import a good fit for structured inbound files that are meant to become new catalog entries rather than being reconciled into existing ones.

### XML Dry Run And Commit Flow

XML import starts with inspection.

The inspection pass reports:

- duplicate ISRCs already present in the catalog
- invalid rows
- missing custom fields
- custom-field type conflicts

If the inspection looks correct, the import can then be committed.

The workflow can also create missing custom fields when allowed. That creation path uses the field types declared by the XML file, including dropdown options when they are present.

### XML Field Handling

The XML importer recognizes supported core fields such as:

- `isrc`
- title or `track_title`
- artist or `mainartist`
- additional artists
- album
- release date, when already in ISO date form
- `iswc`
- `upc` or `upcean`
- genre
- track length
- catalog number
- `buma_work_number`
- custom fields

Rows with invalid or missing essential values are skipped during parsing. Duplicate ISRCs are reported separately during inspection and are not imported again.

### XML Limits

- XML import is not a reconciliation workflow
- XML import does not merge into existing catalog rows
- XML import does not expose per-row manual assignment
- custom field type conflicts must be resolved before import

## Audio Tag Import And Export Metadata Behavior

Audio tag workflows let the app read embedded metadata from supported audio files, while catalog-backed audio export workflows embed trustworthy catalog metadata automatically when they create exported copies.

### Supported Formats

The current audio tag service handles common formats including:

- `mp3`
- `flac`
- `ogg` and `oga`
- `opus`
- `m4a`, `mp4`, and `aac`
- `wav`
- `aif` and `aiff`

### Workflow Behavior

- The app can preview tag data before writing
- The app applies a conflict policy when catalog data and file tags differ
- Catalog-backed audio exports write metadata to exported copies rather than rewriting the source file in place
- Plain external conversion strips inherited source metadata and does not invent catalog metadata

That distinction matters if you want to prepare tagged deliverables without risking the original audio file.

### What This Enables

Audio tag workflows let you keep catalog metadata and file metadata aligned when you are preparing deliverables, checking packaged audio, or exporting catalog-backed audio copies for downstream use.

## Explicit Limits

The current implementation does not do the following:

- it does not provide a row-level manual assignment or reconciliation picker for exchange import
- it does not provide direct third-party integrations with BUMA, STEMRA, SENA, or similar organizations
- it does not treat blob custom fields as tabular import targets
- it does not give JSON or ZIP package imports CSV delimiter controls, because those formats already arrive in a defined structured shape
- it does not treat exchange dry-run as a full row-by-row validation engine
- it does not make release import fill only blank fields; matching releases can be updated from supplied release-row data

Use these boundaries to choose the right workflow for the job.

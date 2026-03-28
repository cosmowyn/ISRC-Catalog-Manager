# Import and Merge Workflows

This guide mirrors the in-app help chapters `Exchange Formats`, `Import and Merge Workflows`, and `Bulk Audio Attach`.

Use `Help > Help Contents` for the integrated manual. This page summarizes how the repository-side import workflows fit together.

## Structured Catalog Exchange

The shared exchange workflow covers:

- XML
- CSV
- XLSX
- JSON
- ZIP package import

The import surface is designed around inspect, review, and apply:

- inspect the incoming payload
- choose the import mode and match rules
- map or skip supported fields where appropriate
- preview the outcome before writes are applied

## Match And Apply Model

The exchange workflow supports:

- `dry_run`
- `create`
- `update`
- `merge`
- `insert_new`

Matching can be based on internal ID, ISRC, UPC/EAN plus title, and supported title/artist heuristics where the importer offers them. The goal is deterministic reviewed intake, not hidden fuzzy mutation.

## Mapping And Saved Choices

CSV and XLSX workflows support mapping presets for recurring sources. The shared exchange setup can also remember per-format choices such as:

- preferred mode
- match posture
- delimiter choice
- custom-field creation posture
- skipped incoming fields

## Package Round-Tripping

ZIP package export and import preserve both data and attachment state.

- binary media is materialized into portable files
- recorded storage mode is preserved on import
- package import restores managed-file and database-backed records through the same reviewed exchange seam

## Reviewed Media Attachment

Media intake for existing tracks uses dedicated reviewed attachment workflows:

- `Bulk Attach Audio Files…` for audio
- `Attach Album Art File…` for single-image artwork

These workflows:

- inspect filenames and supported metadata
- try to match against existing catalog records
- require explicit confirmation before writes
- allow reassignment or skip when the match is not decisive
- let you choose the storage mode for the accepted attachment

Drag-and-drop routes into the same reviewed media-attachment logic rather than a simplified side path.

## Related In-App Help Topics

- `Exchange Formats`
- `Import and Merge Workflows`
- `Bulk Audio Attach`
- `File Storage Modes`

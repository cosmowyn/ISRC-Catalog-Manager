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

## Registry-aware catalog identifier classification

Catalog-number intake is no longer just loose text storage.

During migration, exchange import, and editor-side capture, the shared classifier now decides whether a catalog value should become:

- an `Internal Registry` value
- an `External Catalog` value
- a preserved mismatch that still remains external

Canonical values are accepted as internal when they match:

- a known configured internal category prefix
- the canonical `<PREFIX><YY><NNNN>` structure
- a valid parsed year and sequence

Gaps are allowed. A historical lineage like `ACR250001`, `ACR250005`, and `ACR260009` still imports as internal when those values match the configured category and format. Future generation advances from the stored high-water mark rather than trying to fill numbering gaps automatically.

Values that do not match the internal rules remain safely storable as external catalog identifiers. Known-prefix malformed values are preserved instead of being rejected, and they are flagged as mismatches for later review.

## Match And Apply Model

The exchange workflow supports:

- `dry_run`
- `create`
- `update`
- `merge`
- `insert_new`

Matching can be based on internal ID, ISRC, UPC/EAN plus title, and supported title/artist heuristics where the importer offers them. The goal is deterministic reviewed intake, not hidden fuzzy mutation.

The import report now surfaces identifier outcomes explicitly, including:

- accepted as internal
- stored as external
- flagged mismatch
- skipped
- merged
- conflicted

When the same external catalog value is reused across multiple imported owners, the external catalog surface keeps one shared value with a usage count instead of duplicating it once per owner.

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

- `Code Registry Workspace`
- `Exchange Formats`
- `Import and Merge Workflows`
- `Bulk Audio Attach`
- `File Storage Modes`

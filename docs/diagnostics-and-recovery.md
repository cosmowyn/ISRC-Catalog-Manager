# Diagnostics and Recovery

This guide mirrors the in-app help chapters `Quality Dashboard`, `Diagnostics`, `Undo History and Snapshots`, and `Application Log`.

Use `Help > Help Contents` for the integrated manual. This page summarizes the operational safety surface around the catalog.

## Quality Dashboard Versus Diagnostics

The app separates catalog-content review from environment and storage review.

- `Data Quality Dashboard` focuses on missing identifiers, broken references, missing media, rights issues, asset issues, and other operational catalog blockers
- `Diagnostics` focuses on schema health, storage layout, managed files, history artifacts, migration posture, and repairable environment issues

## Recovery Model

Recovery is layered:

- persistent undo and redo for supported reversible actions
- manual snapshots for higher-risk operations
- restore paths for larger rollbacks
- registered backup artifacts
- cleanup and trim tools with protection rules

## Diagnostics And Repair

Diagnostics can inspect:

- application and profile environment
- schema and SQLite integrity
- foreign keys and custom-value integrity
- managed-file health
- history storage health and budget posture
- staged migration state

Where a repair is safe, diagnostics can offer guided fixes such as history reconciliation, conservative data repair, or staged migration follow-up.

## Logs

The Help menu also exposes local troubleshooting surfaces:

- `Application Log…`
- `Open Logs Folder…`
- `Open Data Folder…`

Use them together with Diagnostics when the issue involves storage, migration, or a failed workflow that needs more than UI-level context.

## Related In-App Help Topics

- `Quality Dashboard`
- `Diagnostics`
- `Undo History and Snapshots`
- `Application Log`

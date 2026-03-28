# Undo, History, and Snapshots

This guide mirrors the in-app help chapter `Undo History and Snapshots`.

Use `Help > Help Contents` for the integrated manual. This page summarizes the recovery model behind the catalog workflows.

## Recovery Layers

The app uses a layered recovery model:

- persistent undo and redo for supported reversible actions
- manual snapshots for higher-risk points in time
- restore paths for larger rollbacks
- backup artifacts for broader safety coverage
- cleanup and trim tools with explicit protection rules

## Why It Matters

Catalog maintenance includes imports, media attachment, settings changes, storage migration, and other actions that can affect more than one table or file. The recovery system is meant to keep those workflows usable and reversible.

## Retention And Cleanup

Recovery includes policy controls as well as point-in-time commands.

- the active profile can store retention and cleanup posture
- cleanup previews what is eligible and what remains protected
- trim focuses on older reversible history while preserving the active branch and dependent artifacts
- budget-aware prompts keep history growth visible instead of silent

## Related In-App Help Topics

- `Undo History and Snapshots`
- `Diagnostics`
- `Application Settings`

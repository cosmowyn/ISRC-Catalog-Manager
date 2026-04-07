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

Registry-backed workflows follow the same model, but with one important distinction: issuing a new internal registry value is append-only. Undo and redo revert the owner links and surrounding editor state instead of editing immutable registry rows in place.

## Why It Matters

Catalog maintenance includes imports, media attachment, settings changes, storage migration, and other actions that can affect more than one table or file. The recovery system is meant to keep those workflows usable and reversible.

## Retention And Cleanup

Recovery includes policy controls as well as point-in-time commands.

- the active profile can store retention and cleanup posture
- cleanup previews what is eligible and what remains protected
- trim focuses on older reversible history while preserving the active branch and dependent artifacts
- budget-aware prompts keep history growth visible instead of silent

For the code registry, that means:

- generated internal codes remain issued even if a later link assignment is undone
- imports can be rolled back by restoring the affected state rather than mutating immutable registry rows
- generated values can remain unlinked if an editor is cancelled after generation
- unused `Registry SHA-256 Key` rows can be deleted manually from the Code Registry Workspace when they are not linked anywhere

## Related In-App Help Topics

- `Code Registry Workspace`
- `Undo History and Snapshots`
- `Diagnostics`
- `Application Settings`

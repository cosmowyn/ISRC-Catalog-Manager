# Code Registry Workflows

This guide mirrors the in-app help for the `Code Registry Workspace`, registry-backed catalog fields, and the registry-aware import flow.

Use `Help > Help Contents` for the integrated manual. This page is the repository-side companion for the code-registry feature set.

## What the registry owns

The code registry is the authoritative home for app-managed internal business codes and generated keys.

Built-in categories include:

- `Catalog Number`
- `Contract Number`
- `License Number`
- `Registry SHA-256 Key`

Custom categories can also be added when you need another app-managed internal code family.

Internal generated codes use the canonical format:

- `<PREFIX><YY><NNNN>`

Examples follow the same structure as `ACR250001`.

## Internal registry versus external catalogs

The registry keeps two distinct concepts separate:

- `Internal Registry`: app-managed identifiers with category rules, configured prefixes, uniqueness, and immutability
- `External Identifiers`: foreign or non-conforming identifier values that still need to be stored safely

This separation is deliberate. Internal generated values remain strongly governed, while external catalog identifiers stay flexible enough for third-party catalog data that does not match the internal scheme.

## Workspace layout

The docked `Code Registry Workspace` is organized into three tabs:

- `Internal Registry`: search, filter by category/year, inspect usage, generate internal codes, generate Registry SHA-256 Keys, link unassigned values, explicitly realign values where allowed, and delete unused unlinked values when safe
- `External Identifiers`: review shared external identifier values, usage counts, provenance/classification notes, promote values into the internal registry, and reclassify canonical candidates after prefix setup changes
- `Categories`: manage built-in and custom categories, edit allowed prefixes, activate/deactivate categories, and remove custom categories when safe

The workspace is meant to be operational, not just administrative. It shows where a value is used and keeps shared identifiers collapsed to one unique row with a usage count instead of duplicating the same catalog value for every linked track or release.

## Working from editors

Registry-backed fields stay available directly in the natural editing workflows:

- `Add Track`
- `Add Album`
- `Edit Track`
- `Release Editor`
- `Contract Editor`
- contract-template drafting through draft-owned registry placeholder generation

Catalog identifier controls support two modes:

- `Internal Registry`: select an existing internal value or generate the next one when the category allows it
- `External Identifier`: type or pick a non-conforming external value without forcing it into the internal rules

Bulk track edit can assign an existing internal value or an external/manual value, but it intentionally does not expose `Generate` to avoid accidental mass issuance.

## Generation and later linking

Generating an internal code or Registry SHA-256 Key creates a real authoritative row immediately. That row is append-only and does not get mutated later.

The same authoritative registry service is also used by the `Contract Template Workspace` when a template contains registry-backed symbols such as catalog numbers, contract numbers, license numbers, or `Registry SHA-256 Key` placeholders. In that workflow, the first saved draft can issue the value and persist it for the draft lifecycle instead of forcing users to pre-generate everything elsewhere.

If a value is generated outside a specific editor context, it can still be assigned later:

- select the value in `Internal Registry`
- use `Link Selected Value`
- choose the target track, release, or contract

This keeps generated values authoritative even when they were issued before the final owner record was chosen.

## Shared catalog usage

When the same catalog identifier is used across related tracks and releases, the registry keeps one shared unique value and reports its usage count. That is especially important for album catalog numbers, where multiple track rows may legitimately point to the same release-level identifier.

## Registry SHA-256 Key versus watermark/authenticity keys

`Registry SHA-256 Key` is a separate registry category for secure generated values stored in the code registry.

It is not:

- the audio watermark key
- the authenticity signing key
- a replacement for the authenticity/provenance workflow

It has separate naming, workspace actions, contract-template behavior, and tests so it stays distinct from the audio authenticity subsystem.

Unused unlinked registry entries can be deleted from the workspace where the current workflow allows it. Linked or otherwise in-use values remain protected.

## Import classification

Exchange import uses the same classifier as migration and editor capture:

- canonical values with a known configured internal prefix and valid `<PREFIX><YY><NNNN>` structure are accepted into the internal registry
- exact existing internal values relink to the existing registry row
- unknown-prefix or non-canonical values are stored as external catalog identifiers
- known-prefix malformed values are preserved safely as external identifiers and flagged as mismatches

Import reports surface the outcome clearly, including counts for:

- accepted as internal
- stored as external
- flagged mismatch
- skipped
- merged
- conflicted

Gaps in numbering are allowed. Future generation continues from the category/year high-water mark rather than backfilling gaps automatically.

## History and cleanup behavior

Registry issuance is append-only. Undo and redo operate on the owner links and surrounding editor state rather than mutating immutable registry rows in place.

That means:

- generated rows can remain intentionally unlinked when an editor is cancelled after generation
- unlinked rows stay visible in the workspace
- relinking can be undone and redone safely
- unused unlinked values can be deleted manually when they are not linked anywhere
- template-generated draft-linked values stay protected while the draft remains in use

## Related docs

- [Repository README](../README.md)
- [Catalog Workspace Workflows](catalog-workspace-workflows.md)
- [Import and Merge Workflows](import-and-merge-workflows.md)
- [Contract Template Workflows](contract-template-workflows.md)
- [Undo, History, and Snapshots](undo_redo_strategy.md)

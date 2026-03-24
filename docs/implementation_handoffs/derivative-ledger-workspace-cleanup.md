# Derivative Ledger Workspace Cleanup Handoff

Date: 2026-03-24

## Status

This handoff documents the Deliverables and Asset Versions cleanup pass currently landing in the repository. The source of truth is the live code in `isrc_manager/assets/dialogs.py`, `isrc_manager/contracts/dialogs.py`, `isrc_manager/parties/dialogs.py`, `isrc_manager/rights/dialogs.py`, `isrc_manager/media/derivatives.py`, `isrc_manager/catalog_workspace.py`, and `ISRC_manager.py`.

The pass is intentionally narrow:

- reduce vertical stacking in the deliverables workspace without hiding any data
- layer the Derivative Ledger into a batch-first workspace instead of one long review column
- keep the ledger operational, searchable, and drill-in friendly
- add safe cleanup/admin actions for stale or test ledger rows
- tighten the spacing and button rhythm in adjacent workspace surfaces that felt over-stretched
- preserve existing browsing, selection, and delete semantics while making them explicit in the UI

This is not a product-wide redesign and not a rewrite of the catalog workspace shell.

## 1. Original Crowding Problems

Before this pass, the deliverables workspace and related manager/dialog surfaces shared the same density pattern:

- search, action rows, tables, and detail text were stacked in a single long column
- the Derivative Ledger exposed both batch browsing and raw detail text at full height all the time
- details were mostly a long plain-text dump, which made scanning harder than necessary
- action rows were visually wide but not meaningfully grouped by task priority
- empty or sparse tables left the surrounding controls feeling like scaffolding instead of a deliberate workspace
- the contract editor and manager panels used enough vertical padding that the active data competed with blank space

The user-visible result was not that data was missing, but that the workspace did too much at once in one vertical line.

## 2. Final Workspace Structure

### Deliverables and Asset Versions

The workspace now splits into two top-level tabs:

1. `Asset Registry`
2. `Derivative Ledger`

The `Asset Registry` tab stays focused on asset/version browsing and editing. The `Derivative Ledger` tab is now a dedicated batch-and-output workspace.

### Derivative Ledger

The ledger now uses a three-layer structure:

1. A compact search strip at the top
2. Always-visible format, derivative-kind, and status filters
3. A primary `Export Batches` table in a left-hand batch browser pane
4. A right-hand `Selected Batch Workspace` with tabs for detail layering

Inside the selected batch workspace, the final tab set is:

- `Derivatives`
- `Details`
- `Lineage`
- `Admin`

That structure keeps the batch list visible while separating routine browsing from deeper inspection and cleanup.

## 3. Tab, Split, and Scroll Decisions

The key structural decision was to stop treating the batch details as a single always-expanded text area.

- The workspace uses a horizontal splitter so the batch list can keep practical row depth while the selected batch workspace stays visible beside it.
- The `Derivatives` tab keeps the operational table and the action cluster together.
- The `Details` tab moves the selected batch summary and selected output metadata into structured fields instead of a plain raw dump.
- The `Lineage` tab keeps hashes, manifests, packaging, and retained path details available without crowding the main review tab.
- The `Admin` tab isolates cleanup actions from normal browsing, so deletion is intentional rather than incidental.
- A dedicated selected-batch heading keeps the current context visible even when operators are moving between tabs.
- Internal scroll areas are used in the deeper tabs so the page does not become one very long scroll column.

The same scroll-and-layering pattern was reused where it helped the contract editor:

- `Links and Parties` now uses a horizontal split between linked repertoire and linked parties
- `Documents` stays on its own workspace page with the document editor as the primary content area

## 4. Admin Tools Added

The ledger is no longer read-only.

Added admin actions:

- `Delete Selected Derivative…`
- `Delete Selected Batch…`
- `Delete Retained Output Files…`
- `Refresh View`

These actions live in the `Admin` tab and are presented as a compact action cluster rather than mixed into normal browsing controls.

The implementation is backed by the ledger service:

- `DerivativeLedgerService.delete_derivative(export_id)`
- `DerivativeLedgerService.delete_batch(batch_id)`
- `DerivativeLedgerService.update_derivative_artifacts(...)`

## 5. Cleanup Semantics and Safety Rules

The cleanup behavior is intentionally conservative.

- Deleting a derivative ledger entry removes the database row only.
- Deleting a batch removes the batch row and its derivative ledger rows from the catalog database only.
- Exported files, ZIP packages, and sidecars remain on disk unless they are deleted separately.
- `Delete Retained Output Files…` is that separate action and keeps the ledger row in place while clearing the retained file references that were actually removed.
- The UI wording makes that distinction explicit before confirmation.
- The delete actions stay disabled until the relevant selection exists.
- No cascading file deletion was introduced by this pass.

The confirmation copy is intentionally blunt:

- derivative deletion says the database record is removed only
- batch deletion says database records are removed only
- both dialogs state that files on disk are not deleted

That keeps the surface honest for stale/test cleanup without implying filesystem changes that are not actually happening.

## 6. Named Surfaces Cleaned Up

### Party Manager

- tightened the `Find and Manage` section
- replaced the stretched button row with a compact action cluster
- kept the table as the visual anchor of the panel

### Rights Matrix

- tightened the `Find and Manage` section
- grouped actions into a compact cluster instead of a wide flat strip
- kept the table dominant and easy to scan

### Edit Contract - Links and Parties

- reduced the empty feeling by splitting linked repertoire from linked parties
- aligned the reference editors and party editor as parallel workspace columns
- replaced the raw party text area with a structured party-role editor that still accepts typed names for new counterparties
- added inline role suggestions and low-noise near-duplicate guidance so typed party names are less likely to create accidental duplicates, including hinting when a likely match is already linked to the current contract and auto-highlighting that linked row below
- preserved role, primary, and notes capture without stretching the tab into a single raw column

### Edit Contract - Documents

- preserved the split document editor structure
- kept the documents table primary and the metadata editor on the side
- improved the internal grouping and spacing in `Document Identity`, `Status and Relationships`, and `Storage and Integrity`
- kept the storage/integrity actions compact and adjacent to the fields they affect

### Deliverables and Asset Versions - Asset Registry

- tightened the `Find and Manage` section
- grouped `Add`, `Edit`, `Delete`, `Mark Primary`, and `Refresh` into a more intentional action cluster
- kept the registry table as the main workspace element
- kept the deliverables workspace in the tabbed dock ecosystem so reopening it reattaches it to the main workspace strip instead of leaving it stranded as a lone dock

### Application Settings - Theme Builder

- restored the hint-text visibility toggle inside the Theme page
- restored the live preview pane as an always-available part of the Theme builder surface by default
- kept preview and hint controls as builder preferences rather than mixing them into saved theme payloads

## 7. Spacing and Layout Rules Introduced

The pass standardizes a few layout rules across the touched surfaces:

- prefer compact action clusters over very wide one-line button bands
- keep section headers close enough to their content to feel connected
- use splitters when two work areas need to stay visible at once
- use internal scroll regions for dense secondary content instead of letting the whole window grow vertically
- keep descriptive text shorter and closer to the active task
- prefer structured fields for review surfaces when the content is meant to be scanned, not read as a blob
- align actions with the controls they act on, rather than floating them below unrelated sections

These rules were applied without inflating padding or hiding information.

## 8. Tests Added or Updated

The main regression anchors for this cleanup are:

- `tests/test_repertoire_dialogs.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/app/_app_shell_support.py`
- `tests/test_theme_builder.py`

The useful assertions to keep in place are:

- the asset browser still exposes both `Asset Registry` and `Derivative Ledger`
- opening the ledger from the shell still lands on the same deliverables panel
- batch selection still updates the derivative view and the detail layer
- ledger format, kind, and status filters reduce the visible batch set without breaking selection state
- the ledger still exposes track, release, and authenticity drill-ins
- retained output file cleanup deletes only files and retained-path references, not the ledger row
- contract editor reference widgets still round-trip known and unresolved IDs
- the structured contract party editor still round-trips known parties and typed-name parties
- the Theme builder keeps both hint toggling and preview-pane behavior available
- reopening the deliverables workspace reattaches it to the tabbed workspace dock strip
- the manager panels still expose their compact action clusters and remain functional with the revised spacing

If more structural coverage is added later, the best targets are the tab names, split layouts, and admin action enablement states rather than pixel-level assertions.

## 9. Files Touched

The implementation work in this pass centers on:

- [`isrc_manager/assets/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/assets/dialogs.py)
- [`isrc_manager/catalog_workspace.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/catalog_workspace.py)
- [`isrc_manager/contracts/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contracts/dialogs.py)
- [`isrc_manager/media/derivatives.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/media/derivatives.py)
- [`isrc_manager/parties/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/parties/dialogs.py)
- [`isrc_manager/rights/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/rights/dialogs.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)

Associated regression coverage lives in:

- [`tests/test_repertoire_dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_repertoire_dialogs.py)
- [`tests/test_theme_builder.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_theme_builder.py)
- [`tests/catalog/_contract_rights_asset_support.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/catalog/_contract_rights_asset_support.py)
- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [`tests/app/test_app_shell_workspace_docks.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

## 10. Future Improvement Opportunities

- consider saved or preset ledger filters once real batch volume grows
- if ZIP-member cleanup is ever added, keep it separate from retained file deletion and make the storage target explicit in the confirmation copy
- if more managers adopt richer cleanup semantics, consider extending the shared confirmation helper into a small reusable confirmation dialog with explicit button labels
- monitor whether the structured contract party editor needs inline merge recommendations across near-duplicate typed names once operators start using it with larger agreements

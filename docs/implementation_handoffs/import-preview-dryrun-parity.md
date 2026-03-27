# Import Preview / Dry-Run Parity

## Scope

This pass standardizes the user-facing import contract across the app:

1. choose source
2. inspect / parse first
3. review preview / dry-run results
4. apply only after explicit review

The work focused on user-facing data imports and preserved existing governance, validation, owner, and repair semantics.

## Import Sections Audited

### Already had inspect + preview before this pass

- Catalog exchange import:
  - `CSV`
  - `XLSX`
  - `JSON`
  - `ZIP/package`
  - `XML`
- Party import:
  - `CSV`
  - `XLSX`
  - `JSON`
- Audio tag import from audio files
- Bulk audio attach workflow

### Lacked full preview-before-apply parity before this pass

- Party import write modes:
  - had source preview and `dry_run`
  - but did not force a dry-run review stage before non-dry-run apply
- Catalog exchange write modes:
  - had source preview and `dry_run`
  - but did not force a dry-run review stage before non-dry-run apply
- Contracts and Rights / Repertoire import:
  - `JSON`
  - `XLSX`
  - `CSV bundle`
  - `ZIP package`
  - previously went from picker straight to apply

### Explicit exceptions

- Track Import Repair Queue replay:
  - this is a repair/reapply surface for already-failed rows, not a normal source-file import
  - it remains an explicit manual repair flow rather than a new file-import preview flow
- Theme import, GS1 helper/template loaders, and other internal/support utilities were audited as non-primary domain import surfaces for this pass

## Shared Import-Preview Contract

All user-facing import workflows covered by this pass now follow one rule:

- parse / inspect first
- review truthful dry-run or inspection output next
- apply only after explicit review acceptance

For Catalog and Party imports, the review stage is a real dry-run executed through the same import service seam that apply uses.

For Contracts and Rights import, the review stage is a parsed inspection/preflight stage that shows entity counts, preview rows, and warnings before apply.

## Party Import Parity Changes

- Party write imports no longer jump from the mapping dialog straight into apply.
- Non-dry-run Party imports now run a dry-run review first using the same Party import service.
- The review dialog summarizes:
  - planned mode
  - rows ready / blocked / skipped
  - would-create / would-update counts
  - owner-binding impact
  - warnings
- Only after that review is accepted does the app submit the write import task.

## Catalog Import Parity Changes

- Catalog write imports now also pause for a dry-run review before apply.
- The same mapping and options are replayed in a dry-run review pass first.
- The review dialog summarizes:
  - planned mode
  - rows ready / blocked / skipped
  - would-create / would-update counts
  - duplicate-safe skips
  - warnings
- Apply only starts after that review is accepted.

## Contracts and Rights / Repertoire Changes

- Added an explicit inspection stage for:
  - `JSON`
  - `XLSX`
  - `CSV bundle`
  - `ZIP package`
- Inspection now:
  - parses the payload first
  - validates schema version
  - summarizes entity counts
  - previews representative entity rows
  - warns about missing packaged files where detectable
- The user now gets a review dialog before the write import starts.

## Truthfulness Changes

- Catalog dry-run now reports planned create/update counts for review.
- Party dry-run now reports planned create/update counts and owner-binding impact.
- Catalog dry-run no longer creates missing custom fields as a side effect.
- Dry-run warnings now explicitly surface missing custom fields that would be created during a real apply.

## Tests Added / Updated

- Added Catalog service coverage proving dry-run stays side-effect free and reports planned changes.
- Added Party service coverage proving dry-run stays side-effect free and reports planned Party changes without binding Owner.
- Added Repertoire service coverage proving inspection previews counts without writing.
- Added app-shell coverage proving:
  - Party write import runs a dry-run review before apply
  - Catalog write import runs a dry-run review before apply
  - Contracts and Rights import now requires review before apply
- Revalidated existing Party import dialog and Catalog import dialog tests.

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/import_review_dialog.py`
- `isrc_manager/exchange/models.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/exchange/repertoire_service.py`
- `isrc_manager/parties/exchange_service.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_json.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/test_repertoire_exchange_service.py`
- `tests/test_party_exchange_service.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`

## Risks / Caveats

- Contracts and Rights review is currently inspection/preflight based rather than a full mutation-simulating dry-run engine.
- The review dialog reuses the existing source-preview information for Catalog and Party imports rather than building a second bespoke per-row action grid.
- Track Import Repair Queue replay remains a repair surface, not a source-file import preview surface.
- Some internal/support loaders were documented as exceptions rather than forced into the domain import contract in this pass.

## Final Contract

User-facing imports now support preview / dry-run review before apply.

In practical terms:

- Party import now reaches a review stage before write apply.
- Catalog import keeps its inspect/mapping flow and now also requires dry-run review before write apply.
- Contracts and Rights import no longer applies directly without review.

No covered user-facing import path now writes domain data directly from file selection without first surfacing a preview / dry-run / review step.

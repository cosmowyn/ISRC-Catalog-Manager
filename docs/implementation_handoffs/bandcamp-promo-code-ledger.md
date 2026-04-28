# Bandcamp Promo Code Ledger

Date: 2026-04-28

## Summary

Added a docked Promo Code Ledger workspace for Bandcamp promo-code CSV exports. The workspace imports Bandcamp code sheets into profile databases, keeps multiple sheets separated, supports filtered/searchable ledger review, and records recipient/redemption edits with undo/redo support.

## User Workflow

- Open from `Catalog > Workspace > Browse / Review > Promo Code Ledger...`.
- Use `Import or Update CSV...` to load a Bandcamp promo-code export.
- New Bandcamp code sets create separate `PromoCodeSheets` rows with child `PromoCodes`.
- Re-importing a matching Bandcamp active-code export updates the existing sheet.
- Bandcamp active-code exports contain only unredeemed codes, so stored codes missing from the new CSV are marked redeemed.
- Codes that reappear in a later active-code export are reactivated and have `redeemed_at` cleared.
- The ledger supports available/redeemed/all filters, fuzzy search, one-click code copy, manual redeemed/available toggles, recipient name, recipient email, and notes.

## Implementation Map

- `isrc_manager/promo_codes/models.py`
  - Dataclasses for sheet records, code records, parsed Bandcamp CSVs, and import/update results.
- `isrc_manager/promo_codes/service.py`
  - CSV parsing, schema safety, import/update logic, sheet matching, list/fetch/update APIs.
  - Sheet matching is scoped by profile when available and uses Bandcamp code-set metadata.
  - Active-code update logic marks missing stored codes as redeemed and reports inserted, marked-redeemed, and reactivated counts.
- `isrc_manager/promo_codes/dialogs.py`
  - Themed dock panel using the app's standard section/header styling.
  - Sheet selector, import/update action, status filter, fuzzy search, table, copy/status actions, and ledger editor.
- `isrc_manager/services/schema.py`
  - Schema target bumped to 42.
  - Adds `PromoCodeSheets` and `PromoCodes` tables plus indexes.
- `isrc_manager/main_window_shell.py`
  - Adds the Catalog workspace action and shortcut.
- `ISRC_manager.py`
  - Wires service lifecycle, dock creation, background import/update, snapshot-history recording, status logging, and ledger edit history.
- `isrc_manager/help_content.py`
  - Adds the in-app help chapter and related overview/shortcut references.
- `pyproject.toml`
  - Includes the new `isrc_manager.promo_codes` package.

## Undo / Redo

- CSV imports and active-code updates run inside `run_snapshot_history_action()` through the background bundle service.
- Ledger edits use `_run_snapshot_history_action()`.
- Undo/redo restores the database snapshot state, including sheet metadata, code availability, redeemed timestamps, and ledger fields.

## Validation Performed

- `ruff check isrc_manager/promo_codes isrc_manager/services/schema.py isrc_manager/main_window_shell.py --select E4,E7,E9,F,I`
- `python -m compileall -q isrc_manager/promo_codes isrc_manager/services/schema.py isrc_manager/main_window_shell.py ISRC_manager.py`
- Service smoke test:
  - import three codes
  - update with two active codes
  - verify the missing stored code is marked redeemed
  - update again with the missing code present
  - verify the code is reactivated
- Snapshot-history smoke test:
  - import
  - active-code update
  - undo
  - redo
- `import ISRC_manager`

## Notes and Caveats

- The importer rejects non-promo Bandcamp CSVs that do not contain promo code rows.
- If more than one stored sheet matches the same update metadata, the service raises an ambiguity error instead of guessing.
- Broad linting of the legacy monolithic `ISRC_manager.py` still reports unrelated pre-existing issues; validation used scoped checks plus compile/import smoke tests.
- The generated HTML help file is rendered from `isrc_manager/help_content.py` at runtime, so no checked-in HTML artifact was updated.

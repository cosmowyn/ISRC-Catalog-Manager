# Import Title/Name Normalization

Date: 2026-03-19

## Summary

This pass adds a narrow import-time capitalization normalization layer for human-readable title/name fields in the exchange import stack.

It builds on `docs/implementation_handoffs/csv-import-delimiter-selection.md` and keeps the current delimiter, duration, merge-matching, and custom-column mapping behavior unchanged.

The enhancement:

- normalizes clearly all-caps title/name values into a display-friendly form
- applies only to an explicit allowlist of human-readable exchange import targets
- preserves existing behavior for codes, identifiers, custom fields, and other non-name fields

## Confirmed Baseline From Prior Handoff

The previous exchange-import pass remains the baseline:

- CSV preview and import still share `inspect_csv()` / `import_csv()` with one delimiter seam
- duration normalization still only targets `track_length_sec`
- merge matching still uses the existing conservative case-insensitive comparison logic
- custom-column mapping still flows through `supported_import_targets()` and the existing `custom::<name>` path

No delimiter UI behavior, duration parsing behavior, merge strategy, or custom-field import architecture was redesigned in this pass.

## Shared Normalization Insertion Point

The new normalization layer lives in `isrc_manager/exchange/service.py`.

Exact seam:

- `_import_rows(...)` now normalizes mapped canonical rows immediately after `_apply_mapping(...)`
- the new helper set is field-aware and import-only

This is the shared seam for:

- CSV exchange import
- XLSX exchange import
- JSON exchange import
- ZIP/package exchange import

This pass does not change import stacks that bypass `ExchangeService`, including:

- `XMLImportService`
- `RepertoireExchangeService`

## Allowlisted Normalized Fields

Only these canonical exchange targets are normalized:

- `track_title`
- `album_title`
- `artist_name`
- `additional_artists`
- `release_title`
- `release_primary_artist`
- `release_album_artist`

`additional_artists` is handled per comma-separated name token and then rejoined as `", "`.

## Explicit Exclusions

The following remain intentionally untouched by this normalization layer:

- `track_id`
- `release_id`
- `isrc`
- `iswc`
- `upc`
- `catalog_number`
- `release_catalog_number`
- `release_upc`
- `buma_work_number`
- all `custom::<name>` fields
- dates, durations, flags, media paths, comments, lyrics, notes, genre, and all other non-allowlisted targets

This keeps identifier and exact-value behavior stable.

## Normalization Rule

The rule is intentionally narrow and deterministic:

- only `str` values in the allowlist are considered
- values are `strip()`-cleaned first
- normalization only triggers when the value contains letters, contains uppercase letters, and contains no lowercase letters
- values that already contain lowercase letters are preserved as-is after trimming
- shouting text is lowercased first, then converted into a simple display case
- capitalization restarts at word starts and after `space`, `-`, `/`, `&`, `(`, `[`, and `"`
- apostrophes are handled narrowly so:
  - `DON'T STOP -> Don't Stop`
  - `O'CONNOR -> O'Connor`
- connector words are lowercased when not first/last:
  - `a`, `an`, `and`, `as`, `at`, `but`, `by`, `for`, `in`, `nor`, `of`, `on`, `or`, `the`, `to`, `via`, `vs`

Examples:

- `DREAMING AWAKE -> Dreaming Awake`
- `THE FOREST OF INFINITE IMAGINATION -> The Forest of Infinite Imagination`
- `JOHN DOE -> John Doe`

## Acronym-Heavy / Symbol-Heavy Behavior

This pass does not add acronym preservation.

Current behavior is intentionally the simple rule output, and that output is locked in tests and documented here:

- `DJ/MC BATTLE -> Dj/Mc Battle`
- `DJ/MC CREW -> Dj/Mc Crew`

Related simple-rule behavior also currently comes out as:

- `R&B NIGHTS -> R&B Nights`
- `AC/DC LIVE -> Ac/Dc Live`

If a later pass needs better acronym handling, it should be treated as a separate follow-up and not bundled into this narrow normalization pass.

## Format Coverage

Covered:

- CSV
- XLSX (the current workbook import path)
- JSON
- ZIP/package exchange imports because they also flow through `_import_rows(...)`

Not covered in this pass:

- XML import
- repertoire exchange import
- any new `.xls` support

## Tests Added Or Updated

Updated:

- `tests/test_exchange_service.py`

New coverage added for:

- CSV import normalization after arbitrary source-column mapping
- XLSX import normalization through the shared exchange seam
- JSON import normalization with a hand-written payload
- all-caps track, album/release, artist, and additional-artist fields
- already-proper or intentionally mixed-case values remaining unchanged
- code/identifier fields remaining unchanged
- acronym-heavy / symbol-heavy fallback behavior being explicit and deterministic

Existing regression coverage left in place:

- delimiter selection and preview/import parity
- duration normalization
- merge matching
- custom-column mapping
- exchange dialog delimiter behavior
- repertoire and XML baseline tests

Focused verification command used for this pass:

- `python3 -m unittest tests.test_exchange_service tests.test_exchange_dialogs tests.test_search_and_repertoire_exchange tests.test_xml_import_service`

## Remaining Limitations

Still intentionally out of scope:

- acronym-preservation logic
- fuzzy or stylistic recasing of already mixed-case values
- locale-aware title-casing
- normalization of arbitrary free text
- normalization of custom fields
- XML import normalization
- repertoire import normalization
- import architecture redesign

# Import Title/Name Normalization

Date: 2026-03-19

## Summary

This follow-up keeps the narrow import-time capitalization normalization layer for human-readable title/name fields in the exchange import stack and adds a conservative acronym/branding-aware refinement.

It builds on `docs/implementation_handoffs/csv-import-delimiter-selection.md` and keeps the current delimiter, duration, merge-matching, and custom-column mapping behavior unchanged.

This follow-up enhancement:

- normalizes clearly all-caps title/name values into a display-friendly form
- restores only exact matched compact acronym compounds from the original import source
- applies only to an explicit allowlist of human-readable exchange import targets
- preserves existing behavior for codes, identifiers, custom fields, and other non-name fields
- moves the XML import action under `File > Import Exchange`
- records the current CI failures and the minimal fixes used to clear them

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
- after the simple display-case pass, exact matched compact acronym compounds from the original all-caps source are restored by source span only
- restoration is limited to compact `/` and `&` compounds with 1-2 letter alphabetic segments:
  - `AC/DC`
  - `DJ/MC`
  - `R&B`
- only the exact matched substring is restored:
  - `AC/DC LIVE SESSION -> AC/DC Live Session`
  - `DJ/MC BATTLE -> DJ/MC Battle`
- neighboring words are not preserved or broadened:
  - `AC/DC LIVE SESSION` does not become `AC/DC LIVE Session`
- standalone short tokens such as `DJ` are still handled by the normal simple title-casing rule
- longer symbolic words such as `ON/OFF` remain outside this narrow preservation rule

Examples:

- `DREAMING AWAKE -> Dreaming Awake`
- `THE FOREST OF INFINITE IMAGINATION -> The Forest of Infinite Imagination`
- `JOHN DOE -> John Doe`
- `AC/DC LIVE -> AC/DC Live`
- `DJ/MC CREW -> DJ/MC Crew`
- `R&B NIGHTS -> R&B Nights`
- `AC/DC Live -> AC/DC Live`

## Acronym-Heavy / Symbol-Heavy Behavior

This follow-up adds conservative acronym preservation for exact matched compact compounds only.

Important boundaries:

- the allowlist of normalized fields is unchanged
- already-correct mixed-case values still bypass normalization
- only the matched compact compound span is restored from the original source
- codes, identifiers, custom fields, comments, lyrics, notes, and all other excluded targets remain untouched

Examples of improved outcomes:

- `DJ/MC BATTLE -> DJ/MC Battle`
- `DJ/MC CREW -> DJ/MC Crew`
- `AC/DC LIVE -> AC/DC Live`
- `R&B NIGHTS -> R&B Nights`

Examples that remain intentionally unchanged or out of scope:

- `AC/DC Live -> AC/DC Live`
- `comments: AC/DC LIVE -> AC/DC LIVE`
- `custom::Mood: R&B NIGHTS -> R&B NIGHTS`

## Format Coverage

Covered:

- CSV
- XLSX (the current workbook import path)
- JSON
- ZIP/package exchange imports because they also flow through `_import_rows(...)`

Not covered in this pass:

- XML import normalization
- repertoire exchange import
- any new `.xls` support

## XML Menu Placement

The XML import workflow itself remains unchanged.

UI change in this follow-up:

- the existing `Import XML…` `QAction` now lives under `File > Import Exchange`
- the action object, label, shortcut, and workflow wiring are preserved
- `App.import_from_xml()` and `XMLImportService` behavior were not changed

Shortcut preserved:

- `Ctrl+Shift+I`
- `Meta+Shift+I`

## Tests Added Or Updated

Updated:

- `tests/test_exchange_service.py`
- `tests/test_app_shell_integration.py`

New coverage added for:

- CSV import normalization after arbitrary source-column mapping
- XLSX import normalization through the shared exchange seam
- JSON import normalization with a hand-written payload
- all-caps track, album/release, artist, and additional-artist fields
- already-proper or intentionally mixed-case values remaining unchanged
- code/identifier fields remaining unchanged
- exact-span acronym compound restoration for `AC/DC`, `DJ/MC`, and `R&B`
- a guard case proving neighboring words are not preserved
- `File > Import Exchange` containing the XML action while preserving the existing XML workflow wiring

Existing regression coverage left in place:

- delimiter selection and preview/import parity
- duration normalization
- merge matching
- custom-column mapping
- exchange dialog delimiter behavior
- repertoire and XML baseline tests

Focused verification command used for this pass:

- `python3 -m unittest tests.test_exchange_service tests.test_exchange_dialogs tests.test_xml_import_service tests.test_app_shell_integration -v`

## CI Findings And Fixes

Current online CI findings investigated on March 19, 2026:

- `CI #94` on commit `d01c613` was already failing `Ruff lint` and `Black format check`
- the current workflow file remained correct; the failures came from code style drift, not workflow configuration
- an older failed run on commit `8164d76` also showed `Tests` and `Coverage` failures, but those were not treated as the current head root cause without fresh reproduction

Locally reproduced causes:

- `python3 -m black --check build.py isrc_manager tests` wanted to reformat:
  - `isrc_manager/paths.py`
  - `tests/test_app_bootstrap.py`
  - `tests/test_history_cleanup_service.py`
  - `tests/test_paths.py`
  - `isrc_manager/history/cleanup.py`
  - `tests/test_storage_migration_service.py`
  - `isrc_manager/storage_migration.py`
  - `isrc_manager/history/dialogs.py`
  - `tests/test_exchange_service.py`
  - `isrc_manager/exchange/service.py`
  - `tests/test_app_shell_integration.py`
- `python3 -m ruff check build.py isrc_manager tests` reported:
  - import ordering issues in `isrc_manager/exchange/service.py`
  - import ordering issues in `isrc_manager/history/dialogs.py`
  - unused imports in `isrc_manager/settings.py`
  - import ordering issues in `tests/test_history_cleanup_service.py`
  - an unused import in `tests/test_storage_migration_service.py`

Fix approach kept intentionally minimal:

- no CI gates were weakened
- no workflow jobs were removed
- only the flagged format/lint drift was corrected
- verification still reran Ruff, Black, mypy, targeted tests, the full unittest suite, and coverage

## Remaining Limitations

Still intentionally out of scope:

- fuzzy or stylistic recasing of already mixed-case values
- locale-aware title-casing
- normalization of arbitrary free text
- normalization of custom fields
- XML import normalization
- repertoire import normalization
- import architecture redesign

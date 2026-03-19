# CSV Import Delimiter Selection And Import Normalization Follow-Up

Date: 2026-03-19

## Summary

This pass builds on `docs/implementation_handoffs/csv-import-column-parsing-fix.md` and keeps the existing exchange CSV parser as the only CSV parsing path.

It adds:

- a compact CSV-only delimiter picker in the exchange import dialog
- preview/import delimiter parity through the shared `inspect_csv()` / `import_csv()` path
- narrow duration normalization for track-length targets during tabular import
- conservative case-insensitive merge matching for title/artist comparisons
- centralized active custom-field mapping targets with regression coverage

## Prior Baseline From The Previous Pass

The prior pass fixed the confirmed semicolon parsing bug in the exchange CSV flow and intentionally deferred manual delimiter override UI.

That baseline remains intact:

- `isrc_manager/exchange/service.py` still owns the single CSV reader seam
- CSV parsing still uses Python's `csv.DictReader`
- quoted fields are still handled by the standard CSV parser
- non-UTF-8 CSV support is still out of scope
- this pass does not add a second parser path or manual string splitting

## Delimiter Picker UI

The delimiter UI was added to `isrc_manager/exchange/dialogs.py` inside `ExchangeImportDialog` on the existing `Setup & Mapping` tab.

Details:

- the controls are CSV-only
- the row sits below the source/warnings row and above mapping presets
- the row contains a delimiter combo plus a custom delimiter text box
- the custom delimiter field is only shown when `Custom delimiter` is selected
- invalid custom delimiter input disables the import button and shows inline validation

`ISRC_manager.py` now passes a CSV reinspection callback into the dialog so delimiter changes refresh the preview through `exchange_service.inspect_csv(...)`.

## Delimiter Flow From Preview To Final Import

Delimiter selection now uses one shared service path from preview through execution.

Flow:

1. `ISRC_manager.py` calls `exchange_service.inspect_csv(path, delimiter=...)`
2. `ExchangeService.inspect_csv()` opens the file through `_open_csv_dict_reader(...)`
3. the resulting `ExchangeInspection` now records `resolved_delimiter`
4. `ExchangeImportDialog` refreshes preview by calling the supplied reinspection callback
5. when the dialog is accepted, `ISRC_manager.py` reads `dlg.resolved_csv_delimiter()`
6. `ISRC_manager.py` passes that delimiter into `exchange_service.import_csv(..., delimiter=...)`
7. `ExchangeService.import_csv()` uses the same `_open_csv_dict_reader(...)` helper as preview

This means preview and final import now use the same resolved delimiter, including Auto detect.

## Supported Delimiters

Supported CSV delimiter options in the dialog are:

- Auto detect
- Comma `,`
- Semicolon `;`
- Tab
- Pipe `|`
- Custom delimiter

Auto detect now considers `,`, `;`, tab, and `|`, with comma fallback if sniffing fails.

## Delimiter Validation Rules

Custom delimiter validation is intentionally narrow:

- custom delimiters must be exactly one character
- empty custom delimiter input is rejected
- newline delimiters are rejected
- tab is rejected in the custom field and must use the predefined `Tab` option
- multi-character custom delimiters are out of scope

The service layer also validates explicit delimiters and raises `ValueError` for invalid input.

## Duration Normalization

Duration normalization was added in `isrc_manager/exchange/service.py` near the existing `track_length_sec` resolution inside `_import_rows(...)`.

The new helper normalizes only values destined for the `track_length_sec` target.

It does not add a generic date/time parsing layer.

## Duration Targets, Supported Inputs, And Limits

Duration normalization applies only when data is mapped into `track_length_sec`.

Supported inputs:

- numeric seconds already suitable for the app/database
- strict `hh:mm:ss` strings, for example `12:34:56`
- `datetime.time` values coming from XLSX cells
- `datetime.timedelta` values coming from XLSX cells

Behavior:

- valid `hh:mm:ss` values are converted to seconds before track payload creation
- already-correct numeric values are preserved
- invalid/non-time text mapped into `track_length_sec` is left unchanged so the existing row failure path handles it
- the existing `track_length_hms` fallback remains in place and still uses the app's existing `parse_hms_text()` helper

Intentional limits:

- no fuzzy duration parsing
- no broad spreadsheet time/date normalization redesign
- no interpretation of unrelated text fields as durations

## Merge Matching Normalization

Merge comparison normalization was added in `isrc_manager/exchange/service.py` inside `_find_existing_track_id(...)`.

Current behavior after this pass:

- internal ID matching is unchanged
- ISRC matching is unchanged
- UPC + title matching is now case-insensitive on title while keeping UPC exact
- merge mode now has a conservative case-insensitive exact title + artist fallback when no earlier match is found
- the merge-only title + artist fallback only auto-matches when it resolves to exactly one existing track

Stored casing is preserved because merge updates continue to reuse the matched track snapshot values for `track_title` and `artist_name`.

## Merge Matching Out Of Scope

Still out of scope:

- fuzzy matching
- approximate similarity matching
- punctuation normalization
- whitespace normalization beyond the existing `strip()`
- broad deduplication logic outside the stated merge comparison changes
- rewriting stored display casing after a successful match

## Custom Columns In Import Mapping

Custom-column mapping remains intentionally narrow and uses the active profile's real custom-field definitions.

This pass centralized the mapping targets through `ExchangeService.supported_import_targets()`, which now supplies:

- all standard exchange import targets
- all active non-blob custom fields as `custom::<name>`

Rules:

- inactive/deleted custom fields are not exposed because the source is `list_active_fields()`
- blob custom fields are still excluded from tabular mapping targets
- duplicates are filtered out before the targets reach the dialog
- the existing `_apply_mapping()`, `_ensure_custom_headers()`, and `_apply_custom_fields()` execution path remains the write path

This was a stabilization/coverage pass, not a redesign of custom-field imports.

## Tests Added Or Updated

Updated:

- `tests/test_exchange_service.py`
- `tests/test_exchange_dialogs.py`

Coverage added for:

- comma, semicolon, tab, and pipe CSV parsing
- explicit custom single-character delimiters
- quoted fields containing active delimiters
- preview/import delimiter parity
- invalid delimiter validation
- `hh:mm:ss` normalization into `track_length_sec`
- XLSX `track_length_sec` normalization from strings, `datetime.time`, and `datetime.timedelta`
- invalid/non-time duration text continuing through the existing row failure path
- case-only merge matching for title/artist
- case-insensitive UPC + title matching
- ambiguous merge matches not auto-merging
- active non-blob custom fields in mapping targets
- arbitrary source-column mapping into `custom::<name>`

Focused verification command used for this pass:

- `python3 -m unittest tests.test_exchange_service tests.test_exchange_dialogs`

## Remaining Limitations

The following remain intentionally out of scope:

- non-UTF-8 CSV encodings
- malformed CSV quoting beyond Python CSV behavior
- multi-character custom delimiters
- GS1/repertoire import redesign
- a broader spreadsheet import overhaul
- generic date/time parsing outside the narrow track-length target fix
- fuzzy title/artist matching
- blob custom fields as tabular import mapping targets

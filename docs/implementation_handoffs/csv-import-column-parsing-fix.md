# CSV Import Column Parsing Fix

Date: 2026-03-19

## Summary Of The Bug

The exchange CSV import flow treated the provided source file as a single-column dataset instead of splitting it into separate fields. In the import dialog this showed up as one long source column header and one long value per preview row, which also meant the real import path received malformed row dictionaries.

## Confirmed Root Cause

The root cause was delimiter handling in the exchange CSV service layer.

- `ISRC_manager.py` calls `exchange_service.inspect_csv(path)` before showing the import dialog.
- `isrc_manager/exchange/dialogs.py` renders whatever headers and preview rows the inspection returns.
- `ISRC_manager.py` later calls `exchange_service.import_csv(path, mapping=mapping, options=options)` to execute the import.
- In `isrc_manager/exchange/service.py`, both `inspect_csv()` and `import_csv()` relied on `csv.DictReader` with comma-based parsing.

That behavior works for comma-delimited CSV files, but it fails for semicolon-delimited CSV files like the reproduced file at `/Users/cosmowyn/Downloads/works-export-2026-03-19.csv`. The file is UTF-8 and properly quoted, so this was not an encoding bug or a preview-mapping bug.

## Affected Files And Modules

- `isrc_manager/exchange/service.py`
- `tests/test_exchange_service.py`
- `docs/implementation_handoffs/csv-import-column-parsing-fix.md`

## Exact Fix Applied

The fix stayed narrowly scoped to the exchange CSV import path.

- Added a shared private helper in `isrc_manager/exchange/service.py` that opens CSV files with the existing `encoding="utf-8-sig"` and `newline=""` settings.
- The helper reads a small sample and uses `csv.Sniffer().sniff(sample, delimiters=",;")` to auto-detect comma or semicolon delimiters.
- If dialect sniffing fails, the helper falls back to standard comma parsing.
- `inspect_csv()` now uses that helper so preview headers and preview rows are parsed with the same detected dialect.
- `import_csv()` now uses that same helper so the actual import path matches the preview path.

No UI behavior, mapping logic, reporting logic, validation rules, or non-CSV exchange formats were changed.

## How The Real CSV Path Now Behaves

For the reproduced file `/Users/cosmowyn/Downloads/works-export-2026-03-19.csv`:

- the delimiter is detected as `;`
- the header row is split into distinct columns
- quoted values are still parsed by Python's standard `csv` module
- the import dialog receives proper source headers and preview rows
- the import step receives properly structured row dictionaries instead of a single combined field

Comma-delimited CSV files still use the same standard parser behavior as before.

## Test Coverage Added Or Updated

Updated `tests/test_exchange_service.py` with coverage for:

- standard comma-delimited header parsing and multi-column preview rows
- quoted comma-containing values in preview parsing
- multi-column comma-delimited create import behavior
- semicolon-delimited inspection parsing
- semicolon-delimited create import behavior

The focused verification commands for this change are:

- `python3 -m unittest tests.test_exchange_service`
- `python3 -m unittest tests.test_exchange_dialogs`

## Assumptions Made

- This fix applies only to the exchange CSV import flow shown in the screenshots.
- GS1 CSV import and repertoire CSV workflows were left unchanged.
- Proper quoted-field handling should continue to rely on Python's standard `csv` module instead of manual string splitting.
- This pass should auto-detect comma and semicolon delimiters only, with comma fallback if detection fails.

## Remaining Limitations And Follow-Up Recommendations

- `csv.Sniffer` is still heuristic, even though it is constrained here to comma and semicolon delimiters.
- Non-UTF-8 CSV encodings are still out of scope.
- Malformed CSV quoting is still handled according to Python's standard CSV parser behavior.
- Manual delimiter override UI was intentionally deferred from this pass to keep the fix limited to the confirmed bug.

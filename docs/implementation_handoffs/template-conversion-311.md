# Template Conversion `3.1.1`

## What Changed

This pass adds a new `File > Conversion…` workflow for template-driven export.

The feature is intentionally separate from both:

- exchange import/export
- plain external audio conversion

It is built for rigid third-party registration or exchange templates where the target structure is supplied externally and the application must fill that structure faithfully rather than exporting the app's own schema.

## Architecture

The implementation is service-first and lives under `isrc_manager/conversion/`.

### New domain/service layer

- `isrc_manager/conversion/models.py`
  - dataclasses for template profiles, source profiles, mapping entries, sessions, previews, and export results
- `isrc_manager/conversion/mapping.py`
  - centralized field normalization, alias-driven matching, transform handling, and mapping-value resolution
- `isrc_manager/conversion/service.py`
  - single orchestration surface for template inspection, source inspection, session building, mapping suggestion, preview compilation, and export writing

### New adapter layer

- `isrc_manager/conversion/adapters/csv.py`
- `isrc_manager/conversion/adapters/xlsx.py`
- `isrc_manager/conversion/adapters/xml.py`
- `isrc_manager/conversion/adapters/database.py`

The adapters own format-specific parsing and faithful writeback rules. The UI does not make direct format decisions.

### New UI layer

- `isrc_manager/conversion/dialogs.py`

`ConversionDialog` reuses the standard dialog chrome and presents four tabs:

- `Template`
- `Source`
- `Mapping`
- `Output Preview`

The dialog is preview-first and sits on the compiled preview model used by export, rather than building a separate display-only preview.

## Supported Formats

### Target templates

- `CSV`
- `XLSX`
- `XLSM` / `XLTX` / `XLTM` through the workbook adapter family
- `XML` with repeat-node templates

### Source files

- `CSV`
- `XLSX`
- `XLSM` / `XLTX` / `XLTM`
- `XML`
- `JSON`

### Database source mode

V1 is intentionally closed to `track-centric` profile rows only.

Database conversion uses `ExchangeService.export_rows(track_ids)` as the canonical flattened source row provider, so release-aware row expansion remains consistent with existing exchange behavior.

## Source Selection And Mapping

### Database record inclusion

Default conversion selection is:

1. current selected catalog tracks, if any
2. else visible filtered rows, if the table is filtered
3. else none

The dialog also exposes:

- the shared `SelectionScopeBanner`
- the shared track chooser for overriding the batch
- per-source-row `Use` checkboxes in the preview table

### Mapping model

Mapping is intentionally closed to three value kinds:

- `source_field`
- `constant_value`
- `unmapped`

Transforms are intentionally closed and service-owned:

- `identity`
- `duration_seconds_to_hms`
- `date_to_year`
- `bool_to_yes_no`
- `comma_join`

Mapping presets are stored in `QSettings`, keyed by template signature plus source mode and target format.

## Preview And Export Behavior

`ConversionPreview` is the export contract.

The preview shown in the dialog is the same compiled structure that the writer uses during export.

### CSV

- preserves detected delimiter and quote behavior
- preserves header order
- replaces the contiguous sample region below the header
- preserves trailing rows after the first blank separator break

### XLSX

- preserves workbook structure and untouched sheets
- selects a writable sheet, with scope choice when more than one candidate exists
- overwrites sample rows under the header
- blanks unused sample rows
- clones row style when more rows are needed than the template already contains

This style-clone behavior intentionally mirrors the existing GS1 workbook export pattern instead of inventing a second workbook row-style approach.

### XML

- intentionally limited to repeat-node templates in this version
- detects candidate repeated record nodes and lets the user choose when ambiguous
- clones the selected sample node per output row
- preserves the rest of the tree
- preserves the XML declaration when present in the template

### Export safety

- export always writes a new output file
- the original template is never overwritten in place
- when a profile is open, export runs through the existing background task plus file-history path
- when no profile is open, export still runs in the background but without profile history recording

## Menu, Styling, Help, And Versioning

### File menu

- added top-level `File > Conversion…` in `isrc_manager/main_window_shell.py`
- placed after `Export` and before the maintenance separator

### Styling / theme-builder integration

The dialog reuses the standard theme-builder patterns instead of adding one-off styling logic.

Key hooks:

- dialog chrome via `_apply_standard_dialog_chrome`
- header via `_add_standard_dialog_header`
- tab pages marked with `role="workspaceCanvas"`
- object names for the conversion tables and XML preview so styling remains inspectable and consistent

No custom stylesheet-only workaround path was added.

### Help and repo docs

Updated:

- `isrc_manager/help_content.py`
  - new `conversion` chapter
  - updated `overview`
  - updated `exchange-formats`
  - updated `import-workflows`
- `docs/README.md`
- new repo guide: `docs/template-conversion-workflow.md`

### Version `3.1.1`

Updated in surfaced runtime/package locations:

- `pyproject.toml`
- `ISRC_manager.py`
- `isrc_manager/tasks/app_services.py`
- `isrc_manager/exchange/master_transfer.py`
- surfaced version docs and test expectations

## No Schema Migration

This feature introduces no profile-schema migration.

Rationale:

- conversion sessions are transient
- mapping presets live in `QSettings`
- export output is written to new files only
- no new persistent profile entities were required for V1

That keeps the feature additive and avoids introducing database risk for a first conversion release.

## Files And Layers Touched

### New

- `isrc_manager/conversion/__init__.py`
- `isrc_manager/conversion/models.py`
- `isrc_manager/conversion/mapping.py`
- `isrc_manager/conversion/service.py`
- `isrc_manager/conversion/dialogs.py`
- `isrc_manager/conversion/adapters/__init__.py`
- `isrc_manager/conversion/adapters/base.py`
- `isrc_manager/conversion/adapters/csv.py`
- `isrc_manager/conversion/adapters/xlsx.py`
- `isrc_manager/conversion/adapters/xml.py`
- `isrc_manager/conversion/adapters/database.py`
- `docs/template-conversion-workflow.md`
- `tests/test_conversion_service.py`
- `tests/test_conversion_dialog.py`
- `tests/test_main_window_shell_conversion.py`

### Updated

- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`
- `isrc_manager/tasks/app_services.py`
- `isrc_manager/help_content.py`
- `isrc_manager/exchange/master_transfer.py`
- `pyproject.toml`
- `docs/README.md`
- surfaced version docs/readmes
- relevant tests

## QC Checks Performed

- audited live menu wiring before editing
- audited current exchange import/export and GS1 workbook patterns before adding conversion logic
- centralized mapping, transform, and format decisions into the conversion service and adapters
- verified the preview model is the exact model used by export
- verified source-mode switching keeps file and database source state separate
- verified conversion default selection order matches the agreed current-selection-first contract
- verified the dialog uses existing theme-builder roles and object naming instead of ad hoc styling
- verified the version bump is consistent across runtime/package surfaces touched in this pass

## QA Checks Performed

Validated headlessly:

- CSV template parsing and dialect-preserving export
- XLSX inspection/export plus appended row style cloning
- XML repeat-node inspection/export with declaration preservation
- source parsing for CSV/XLSX/XML/JSON
- database-backed source population through `ExchangeService.export_rows`
- row inclusion toggles in the source preview
- manual mapping override and constant-value export behavior
- File-menu `Conversion…` action wiring through a lightweight shell-composition test
- help topic rendering and diagnostics version surface checks

## Tests Added Or Updated

Added:

- `tests/test_conversion_service.py`
- `tests/test_conversion_dialog.py`
- `tests/test_main_window_shell_conversion.py`

Updated:

- `tests/test_help_content.py`
- `tests/test_build_requirements.py`
- `tests/test_app_dialogs.py`

Headless validation run:

- `python3 -m py_compile` on the new conversion modules and updated targeted tests
- `./.venv/bin/ruff check isrc_manager/conversion ...`
- `./.venv/bin/black --check isrc_manager/conversion ...`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m unittest tests.test_conversion_service tests.test_conversion_dialog tests.test_help_content tests.test_build_requirements tests.test_main_window_shell_conversion`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m unittest tests.test_app_dialogs.AppDialogsTests.test_help_contents_dialog_filters_and_opens_topics tests.test_app_dialogs.AppDialogsTests.test_diagnostics_dialog_uses_async_loader`

Observed result:

- `41` targeted tests passed

## Relation To Previous Handoffs

This patch follows the existing product direction from prior exchange, GS1, and external-identifier work rather than replacing it.

It deliberately preserves previous intent:

- exchange import/export remains the app-schema portability workflow
- GS1 workbook export remains its own governed template workflow
- external audio conversion remains metadata-free media conversion
- Codespace/external identifier changes remain untouched by this feature

The new conversion system reuses patterns from exchange preview/mapping and GS1 workbook fidelity, but it does not bypass or rewrite those workflows.

## Known Edge Cases / Follow-Up Risks

- CSV template detection still assumes the first non-empty row is the header row. That matches the current contract, but future support for comment-prefixed or multi-header CSV templates may need a richer detector.
- XML support is intentionally limited to repeat-node templates. Arbitrary whole-tree XML mapping is not implemented in this release.
- Database source mode is intentionally track-centric. Multi-entity conversion sources are a future extension, not a silent partial capability.
- Mapping presets are stored in `QSettings`, so they are machine-local rather than profile-portable.
- The broader app-shell startup suite was not used as the primary verification surface for this feature in this environment; a dedicated lightweight menu-composition test was added instead to keep File-menu wiring coverage deterministic and headless.

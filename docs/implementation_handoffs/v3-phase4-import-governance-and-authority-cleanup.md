# V3 Phase 4 Import Governance And Authority Cleanup

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status

This handoff is `in_progress`.

It records the first completed import-governance unification slice inside Phase 4:

- supported catalog XML import now uses the same reviewed exchange setup surface as the tabular catalog import formats
- shared exchange create-mode imports now attach or create a governing `Work` per imported track
- imported artist identity now resolves through `Party` authority and auto-creates missing artist parties when needed

The remaining Phase 4 cleanup, especially obsolete legacy license archive retirement, is still pending.

## Import Paths Audited

Track-creating or track-populating catalog import paths audited in the live repo:

- `ExchangeService.import_csv()`
- `ExchangeService.import_xlsx()`
- `ExchangeService.import_json()`
- `ExchangeService.import_package()`
- `App.import_from_xml()` plus `XMLImportService.execute_import()`

Audited but not part of the track-creation problem:

- `RepertoireExchangeService` imports for parties, works, contracts, rights, and assets
- audio-tag import, which updates existing rows rather than creating new catalog tracks through the exchange importer

## Import Bypasses Found Before This Slice

Before this slice, the main bypasses were:

- `ExchangeService._import_rows()` created new tracks directly from imported row payloads with no guaranteed `Work` attachment
- `ExchangeService._import_rows()` did not resolve imported artist identity through `Party` authority before creating new rows
- `App.import_from_xml()` launched a separate XML-only inspection and import path instead of the shared mapping UI
- `XMLImportService.execute_import()` inserted directly into `Tracks` from parsed XML rows without `Work` governance or Party-backed identity resolution

## Governed Import Routing Now

The corrected import behavior now works like this:

1. `CSV`, `XLSX`, `JSON`, `ZIP package`, and `XML` catalog imports all use the exchange inspection and mapping surface.
2. XML still performs schema-aware preflight first, but that preflight now feeds the same reviewed mapping dialog instead of replacing it.
3. Shared create-mode exchange imports now run through `GovernedImportCoordinator` before saving tracks.
4. For each created imported track, the importer now:
   - resolves the main artist through `Party`
   - resolves additional artists through `Party`
   - attaches an existing `Work` when a deterministic work match is available
   - otherwise creates a new `Work` seeded from imported track metadata
   - writes the new track with `work_id` immediately
5. For matched updates and merges:
   - existing governed tracks keep authoritative `Work` composition data
   - orphaned matched tracks can be governed during import instead of remaining detached

## XML Integration Model

XML no longer acts like a separate insert-only UI workflow.

The new user-facing XML flow is:

- `File > Import & Exchange > Catalog Exchange > Import XML…`
- XML parser preflight
- shared exchange mapping dialog
- shared import mode selection
- shared governed import execution

XML-specific behavior that remains intentionally preserved:

- supported XML schema detection
- duplicate and invalid row counts in inspection
- custom-field type conflict reporting
- typed missing custom-field creation when allowed

## Party-Backed Identity Resolution And Auto-Creation

Imported artist identity is now normalized through `Party` authority during create-mode import.

Current behavior:

- main artist names are resolved through `PartyService.ensure_party_by_name(...)`
- additional artist names are resolved the same way
- missing artist parties are auto-created when needed
- the track row still stores the resolved artist display text for the legacy recording-side artist columns, but the canonical identity authority is now seeded from `Party`

This slice does not yet add a broader ambiguous-identity resolution queue for imports. The current behavior is deterministic auto-create for straightforward artist-name imports.

## Track To Work Seeding During Import

When the importer creates a new `Work` from imported track data, it seeds:

- `Work.title <- imported track title`
- `Work.iswc <- imported iswc`
- `Work.registration_number <- imported buma_work_number`
- `Work` contributor rows from imported `composer` / `publisher` fields when those fields exist in the source format

This keeps imported track creation aligned with the v3 governed model and avoids a second manual governance pass just to attach imported rows to works.

## Remaining Phase 4 Authority Cleanup Completed In This Slice

This slice also completed these coherence updates:

- `Import XML…` now behaves like the other exchange imports in menu structure and UX
- exchange dialog wording now uses the generic `Create missing custom fields` label for XML
- help and README copy now describe XML import as part of the shared exchange setup surface, not as a separate special importer

## Obsolete Legacy License Archive Menu Retirement

Not completed in this slice.

Still pending:

- `Catalog -> Legacy License Archive -> Browser`
- `Catalog -> Legacy License Archive -> Migrate`

These remain the next obvious Phase 4 cleanup target.

## Files Changed In This Slice

- `ISRC_manager.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/exchange/dialogs.py`
- `isrc_manager/services/imports.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/help_content.py`
- `README.md`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_xml_import.py`
- `tests/test_exchange_dialogs.py`
- `tests/app/_app_shell_support.py`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-phase4-import-governance-and-authority-cleanup.md`

## Tests Added Or Updated

- exchange CSV create coverage now asserts imported rows get a parent `Work` and canonical artist `Party`
- new exchange XML coverage verifies:
  - XML inspection now produces exchange-style mapping preview data
  - XML import creates missing custom fields when allowed
  - imported XML rows create a parent `Work`
  - imported XML artist identities auto-create `Party` records
- exchange dialog coverage verifies XML uses the shared exchange dialog wording for missing custom fields
- app-shell startup coverage verifies XML now lives under the shared `Catalog Exchange` import menu path

Validation run:

- `python3 -m unittest tests.exchange.test_exchange_csv_import tests.exchange.test_exchange_xml_import tests.test_exchange_dialogs tests.test_xml_import_service`
- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m unittest tests.exchange.test_exchange_json tests.exchange.test_exchange_package tests.test_catalog_workflow_integration tests.test_xml_export_service tests.test_help_content`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`

## Risks And Caveats

- the legacy `XMLImportService.execute_import()` implementation still exists for compatibility tests and parser reuse, but the intended user-facing import route is now the shared exchange surface
- imported XML custom fields that are missing from the current profile must either be created or explicitly skipped; the importer no longer silently invents a second XML-only custom-field prompt flow
- `Party` auto-creation is deterministic name-based seeding, not a human-reviewed ambiguity queue
- broader legacy license archive retirement is still outstanding

## Exact Safe Pickup Instructions

1. read [`v3-workflow-revision-phase-4.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-phase-4.md) first
2. treat this handoff as the import-governance checkpoint for the current Phase 4 slice
3. do not reopen a separate XML-only importer UI
4. continue from the remaining Phase 4 cleanup targets:
   - legacy license archive browser/migrate retirement
   - remaining outward-facing authority reads that still prefer track-side composition shadow fields
   - any remaining import-repair bypasses that still avoid the governed model

## QA/QC Summary From Central Oversight

This slice corrected the biggest remaining import-shape inconsistency without creating a second governance model:

- XML import now behaves like the other catalog exchange imports from the user’s perspective
- imported tracks now follow the same governed model as manual creation by ending with a linked or newly created parent `Work`
- imported artist identity is now Party-backed and can auto-create missing parties when needed
- the app remains in a stable working state after the XML/exchange unification

Explicit statement of current truth:

Imported tracks now follow the same governed model as manual creation. They do not remain orphaned from `Work`, and XML no longer bypasses the shared mapping/import pipeline.

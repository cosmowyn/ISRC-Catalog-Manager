# V3 Governed Track Creation Invariant Enforcement

## Status And Scope

This pass enforces the v3 product invariant that new tracks must not be created without a linked governing `Work`.

Scope for this pass:

- single-track creation
- album/batch creation
- exchange import create paths
- legacy XML import create paths
- background-task service wiring for import/create surfaces
- service-level integrity enforcement for new track creation

This pass intentionally does not broaden into final schema hardening or historical orphan-data cleanup.

## Source Of Truth

Runtime files:

- `ISRC_manager.py`
- `isrc_manager/services/import_governance.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/services/imports.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/tasks/app_services.py`
- `demo/build_demo_workspace.py`

Tests:

- `tests/test_governed_track_creation_service.py`
- `tests/test_track_service.py`
- `tests/test_xml_import_service.py`
- `tests/exchange/test_exchange_csv_import.py`
- `tests/exchange/test_exchange_xlsx_import.py`
- `tests/exchange/test_exchange_xml_import.py`
- `tests/exchange/test_exchange_package.py`
- `tests/exchange/test_exchange_merge_mode.py`
- `tests/exchange/test_exchange_json.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/test_work_and_party_services.py`
- `tests/test_quality_service.py`

## Product Rule Enforced

The enforced rule is now:

- every newly created `Track` must complete creation with a valid linked `work_id`

Allowed outcomes:

1. link the track to an existing `Work`
2. create a new `Work` from the track payload and link the track immediately

Disallowed outcome:

- save a new `Track` row with no valid linked `Work`

If governance cannot be resolved, track creation now fails instead of saving an orphan row.

## Track-Creation Paths Audited

The following runtime paths were audited:

- `Add Track` single-item creation in `ISRC_manager.py`
- `Add Album` batch creation in `ISRC_manager.py`
- exchange create-mode imports in `isrc_manager/exchange/service.py`
- XML import through `isrc_manager/services/imports.py`
- background-task service instantiation in `isrc_manager/tasks/app_services.py`
- demo workspace generation in `demo/build_demo_workspace.py`
- low-level track row creation in `isrc_manager/services/tracks.py`

Import formats and surfaces covered by the audited exchange/import runtime:

- CSV
- XLSX
- JSON
- ZIP / package exchange import
- XML exchange import

Note:

- `.xls` is not a live runtime import path in the current repository. The supported spreadsheet path is `.xlsx`.

## Governance Bypasses Before This Pass

The audit found several ways the invariant could still be bypassed:

- `TrackService.create_track()` could still create a new track with `work_id=None` unless the caller enforced governance first
- `Add Track` and `Add Album` were applying governance in workflow code, but not through one shared mandatory creation seam
- exchange create-mode imports were still split between work-resolution helpers and raw track creation instead of one shared governed create call
- legacy `XMLImportService.execute_import()` still inserted track rows directly and could create ungoverned tracks
- background-task service wiring did not consistently construct import services with the same governed creation dependencies
- demo/build helper creation still bypassed the governed seam

## Shared Governed Creation Mechanism Implemented

The systemic fix is centered in `isrc_manager/services/import_governance.py`.

New shared governed creation entrypoints:

- `GovernedImportCoordinator.create_governed_track(...)`
- `GovernedImportCoordinator.create_governed_tracks_batch(...)`
- `GovernedImportCoordinator.resolve_governed_work(...)`
- `GovernedImportCoordinator.resolve_governed_work_id(...)`
- `GovernedImportCoordinator.build_work_payload_from_track(...)`

This is now the shared creation seam for both manual and imported track creation.

### Governance Resolution Order

For each incoming track payload, work governance now resolves in this order:

1. explicit existing `work_id`
2. explicit `create_new_work` mode
3. safe `match_or_create_work` resolution for import flows
4. create a new `Work` from the track payload when no existing work is safely resolved

Track creation only proceeds after a valid `work_id` is obtained.

### Batch Behavior

Batch creation now uses `create_governed_tracks_batch(...)`, which applies the same invariant row by row.

That keeps `Add Album` and multi-row import creation aligned with the same product rule:

- each created track ends governed
- no row is saved first and "fixed later"

## How Manual Creation Was Corrected

### Add Track

`ISRC_manager.py` now routes the single-track save flow through `self.governed_track_creation_service.create_governed_track(...)`.

That replaced duplicated "maybe create work, then create track" logic with one shared governed creation path.

### Add Album

Album/batch save now routes through `self.app.governed_track_creation_service.create_governed_tracks_batch(...)`.

This removed row-by-row duplicated work creation logic and ensures the same invariant applies to batch track creation.

## How Import Formats Were Corrected

### Exchange Imports

`isrc_manager/exchange/service.py` now uses the shared governed creation seam for create-mode imported rows:

- CSV
- XLSX
- JSON
- ZIP / package import
- XML exchange import

Instead of separately resolving a work and then calling raw track creation, the exchange service now calls `create_governed_track(...)` directly.

### Legacy XML Import

`isrc_manager/services/imports.py` no longer inserts `Tracks` rows directly during XML import.

`XMLImportService.execute_import()` now:

- normalizes imported row data into a `TrackCreatePayload`
- routes the row through `GovernedImportCoordinator.create_governed_track(...)`
- applies custom fields only after the governed track exists

### Background Task Service Wiring

`isrc_manager/tasks/app_services.py` now constructs:

- `TrackService(..., require_governed_creation=True)`
- `XMLImportService(...)` with `party_service`, `work_service`, and `profile_name`
- `ExchangeService(...)` with the same governed dependencies

That keeps background import execution aligned with the main runtime invariant.

## Track -> Work Seeding Behavior

When a new `Work` is created from a track payload, the shared coordinator auto-seeds the work from the incoming track data.

Seeded/shared fields include:

- work title from track title
- `iswc`
- work registration number
- profile name
- composer/publisher contributor context already available in the track/import payload

Party-backed artist handling is preserved by resolving artist identities through the existing party-aware path before work creation and track save complete.

## Integrity Enforcement Added

### Service-Level Enforcement

`isrc_manager/services/tracks.py` now supports:

- `TrackService(..., require_governed_creation=True)`

When enabled, low-level track creation validates that:

- new tracks must provide a non-null `work_id`
- the referenced `Work` row must exist

This validation is enforced inside `TrackService` before the row insert completes.

The live app and background task services now enable this flag.

### Why Full Schema Hardening Was Not Applied

The current schema still allows nullable `Tracks.work_id`, and broad schema hardening was not safe in this pass because:

- existing compatibility/lifecycle semantics still permit nulling in some legacy flows
- full `NOT NULL` / global foreign-key tightening needs a separate cleanup pass
- destructive/unlink lifecycle behavior was not reworked here

So the strongest safe enforcement applied in this pass is:

- central governed creation
- guarded service-level validation in production services

## Tests Added Or Updated

Added:

- `tests/test_governed_track_creation_service.py`

Updated:

- `tests/test_track_service.py`
- `tests/test_xml_import_service.py`
- `tests/app/_app_shell_support.py`

Validated exchange/import coverage:

- `tests/exchange/test_exchange_csv_import.py`
- `tests/exchange/test_exchange_xlsx_import.py`
- `tests/exchange/test_exchange_xml_import.py`
- `tests/exchange/test_exchange_package.py`
- `tests/exchange/test_exchange_merge_mode.py`
- `tests/exchange/test_exchange_json.py`

Validated workflow/non-regression coverage:

- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/test_work_and_party_services.py`
- `tests/test_quality_service.py`

Validation runs used in this pass:

- `python3 -m unittest tests.test_governed_track_creation_service tests.test_xml_import_service tests.test_track_service tests.exchange.test_exchange_csv_import tests.exchange.test_exchange_xlsx_import tests.exchange.test_exchange_package tests.exchange.test_exchange_xml_import tests.exchange.test_exchange_merge_mode tests.exchange.test_exchange_json`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces`
- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.test_catalog_workflow_integration`
- `python3 -m unittest tests.test_work_and_party_services`
- `python3 -m unittest tests.test_quality_service`
- `python3 -m black --check ISRC_manager.py demo/build_demo_workspace.py isrc_manager/exchange/service.py isrc_manager/services/import_governance.py isrc_manager/services/imports.py isrc_manager/services/tracks.py isrc_manager/tasks/app_services.py tests/app/_app_shell_support.py tests/test_track_service.py tests/test_xml_import_service.py tests/test_governed_track_creation_service.py`

## Risks And Caveats

- This pass blocks new orphan track creation through the live governed creation/runtime services, but it does not retroactively repair old orphan data.
- The schema itself is not yet globally hardened to `NOT NULL` on `Tracks.work_id`.
- Historical restore/snapshot-style legacy replay paths were not fully reworked in this pass; they should be treated as follow-up risk if they can replay pre-invariant orphan state.
- Existing unlink/delete lifecycle behavior around already-created tracks was not comprehensively redesigned here; this pass is specifically about creation invariants.
- `.xls` is not a currently supported runtime import path, so the spreadsheet coverage in this repository is `.xlsx`.

## QA/QC Summary

Central Oversight conclusion:

- new track creation now flows through one governed creation rule instead of scattered UI/import heuristics
- manual single-track creation, album/batch creation, exchange imports, and XML import now converge on the same governed creation seam
- live production services now reject new orphan-track creation at the service layer when governance is missing
- the app no longer relies on "save track first, repair work later" for supported new creation/import paths

## Explicit Product-State Statement

New tracks can no longer be created without a linked `Work` across the supported manual and import creation formats in this repository.

That includes:

- `Add Track`
- `Add Album`
- CSV import
- XLSX import
- JSON import
- ZIP / package import
- XML import

For each newly created track, the creation transaction now either:

- links to an existing `Work`
- or creates and links a new `Work`

The supported creation/import runtime no longer saves new orphan tracks as an acceptable outcome.

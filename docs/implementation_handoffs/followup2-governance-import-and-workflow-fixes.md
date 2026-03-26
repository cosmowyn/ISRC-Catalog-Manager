# Follow-up 2: Governance, Import Progress, and Workflow Fixes

## Issues Categorized

This pass grouped the requested work into five related buckets:

1. Track/work governance and live-catalog protection
2. Import-progress lifecycle and loading ownership
3. Work Manager visibility/state behavior
4. Owner/signer and contributor workflow defaults
5. Intent-based menu organization

## Root Causes Found

### Governance / repair path

- The shared governed creation seam already existed, but failed import rows were only reported as warnings in the catalog exchange flow.
- That meant a row could be blocked correctly without entering the live catalog, but the failed row was not persisted anywhere repairable.
- The lower-level XML helper path also lacked a persistent repair outcome for blocked rows.

### Import progress

- Catalog exchange already had the right background-task shell, but not every import worker forwarded real progress callbacks into the service layer.
- Party import services already supported staged progress, but the UI worker still only set status text.
- Repertoire import still ran on the UI thread and bypassed the managed background-task lifecycle entirely.

### Work Manager visibility

- Work Manager browsing and linked-track focus had drifted together.
- The panel could still behave like a scoped linked-track view instead of a reliable stored-works catalog view.
- Stale search text also persisted across generic reopen flows.

### Signer / contributor defaults

- Authenticity key generation still defaulted to a blank signer even though owner identity is now Party-backed.
- Contributor rows still opened with blank split values and had no equal-split tool.

### Menus

- Export menus were still format-first instead of scope-first.
- Workspace actions mixed manager openers with panel toggles.
- The repair queue had no durable intent-based menu entry.

## Governance Fixes Landed

### Hard live-catalog rule

- Track-import rows now enter the live catalog only after governed creation succeeds with a valid `work_id`.
- Failed catalog exchange rows do not create live orphan tracks.

### Persisted repair queue

- Added `TrackImportRepairQueue` as a persisted subsystem.
- Added `TrackImportRepairQueueService` in:
  - `isrc_manager/services/import_repair_queue.py`
- Added schema support and migration to schema target `34`.
- Catalog exchange imports now persist failed track-import rows into the repair queue instead of silently discarding them.
- The returned `ExchangeImportReport` now carries `repair_queue_entry_ids`.
- Import completion reporting now exposes repair-queue counts and offers a direct `Open Repair Queue` path.

### Repair replay

- Added repair UI in:
  - `isrc_manager/exchange/repair_dialogs.py`
- Repair rows can be edited, optionally linked to an existing Work, and replayed through the same governed creation seam via `ExchangeService.import_prepared_rows(...)`.
- Successful replay resolves the queue entry instead of leaving it pending.

### XML helper path

- `XMLImportService.execute_import()` now also persists blocked rows to the same repair queue for helper/runtime consistency.
- Blocking custom-field validation failures queue the rows before raising.

### Track -> Work metadata seeding

- `build_work_payload_from_track(...)` now seeds additional safe shared metadata:
  - `genre_notes`
  - `notes`
  - `lyrics_flag`

## Import Progress Dialog Fixes Landed

### Catalog exchange

- Catalog exchange already used the managed background-task dialog; this pass kept that shell and extended the stage reporting.
- Progress now reports determinate stages through `100%`, including row-apply progress and finalization.

### Party import

- Party inspection and Party import workers now forward `ctx.report_progress` / `ctx.raise_if_cancelled` into `PartyExchangeService`.
- Party import loading now shows real staged progress instead of only status text.

### Repertoire import

- Repertoire import now runs through `_submit_background_bundle_task(...)` instead of the UI thread.
- `RepertoireExchangeService` now reports staged determinate progress for:
  - read / extract
  - parse
  - Parties
  - Works
  - Contracts
  - contract-document relink
  - Rights
  - Assets
  - finalize
- Progress now reaches `100%`.

## Signer Default Fix

- `AuthenticityKeysDialog` now resolves the signer label from Party authority.
- If a current owner Party exists, that Party’s primary label is used as the default signer label.
- If no owner Party exists:
  - a dropdown is shown
  - choices come from Party records
  - no fallback signer identity is invented
- If no Parties exist, key generation is blocked with a clear message.

## Contributor Split Workflow Improvements

- New contributor rows now default:
  - `Share %` = `100`
  - `Role Share %` = `100`
- Added equal-split tools in `WorkEditorDialog`:
  - `Equal Split Share`
  - `Equal Split Role Share`
  - `Equal Split Both`
- Equal split:
  - uses assigned contributor rows
  - distributes to two decimal places
  - assigns rounding remainder to the last row
  - preserves exact `100.00` totals

## Work Manager Visibility Fix

- `WorkBrowserPanel.refresh()` now uses the stored Works list for normal browsing instead of linked-track filtering.
- Opening Work Manager from a linked track now uses linked-track context only to focus the relevant Work when possible.
- Generic Work Manager opens clear stale search text and restore the stored-works view.

## Menu Organization Changes Made and Why

The menu pass was intentionally narrow and route-preserving.

### Catalog > Workspace

- Split into:
  - `Open and Manage`
  - `Panels`
- This separates “open a manager/workspace” from “toggle a panel”.

### Catalog > Quality & Repair

- Added:
  - `Track Import Repair Queue…`
- This gives the repair path a durable review-oriented home instead of leaving it hidden behind import fallout.

### File > Export > Catalog Exchange

- Reorganized to:
  - `Current Scope`
  - `Full Catalog`
- Existing export actions and routes were preserved.

### File > Export > Parties

- Reorganized to:
  - `Selected Parties`
  - `Full Party Catalog`
- Existing export actions and routes were preserved.

### View

- Removed `Show Add Track Panel` from `View`.
- `View` now stays focused on visibility/layout/chrome instead of workspace workflow toggles.

## Tests Added / Updated

### Governance / repair queue

- Added exchange tests proving:
  - failed import rows go to the repair queue
  - no live orphan track is created
  - repair replay uses the governed seam and resolves the queue row
- Added XML helper coverage proving blocked rows are queued before raising.

### Metadata seeding

- Extended governed creation coverage to assert seeded Work metadata now includes:
  - `genre_notes`
  - `notes`
  - `lyrics_flag`

### Import progress

- Added staged-progress coverage for:
  - catalog exchange import
  - Party import
  - repertoire import

### Signer / contributor

- Added authenticity dialog coverage for:
  - owner-backed signer default
  - Party dropdown fallback
  - no-Party blocking behavior
- Added Work editor coverage for:
  - default `100` split values
  - equal split behavior for both columns

### Work Manager / menus

- Added Work Manager coverage proving stored Works remain visible without linked-track narrowing.
- Updated app-shell menu tests for:
  - scope-first export grouping
  - workspace open/manage vs panel grouping
  - repair queue menu exposure
  - moved routing preservation

## Validation Run

- `python3 -m black --check ISRC_manager.py isrc_manager/authenticity/dialogs.py isrc_manager/exchange/models.py isrc_manager/exchange/repertoire_service.py isrc_manager/exchange/service.py isrc_manager/main_window_shell.py isrc_manager/parties/exchange_service.py isrc_manager/services/__init__.py isrc_manager/services/import_governance.py isrc_manager/services/import_repair_queue.py isrc_manager/services/imports.py isrc_manager/services/schema.py isrc_manager/tasks/app_services.py isrc_manager/works/dialogs.py isrc_manager/exchange/repair_dialogs.py tests/exchange/_support.py tests/exchange/test_exchange_json.py tests/exchange/_repertoire_exchange_support.py tests/exchange/test_repertoire_exchange_service.py tests/test_party_exchange_service.py tests/test_repertoire_dialogs.py tests/test_xml_import_service.py tests/test_governed_track_creation_service.py tests/test_authenticity_dialogs.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py tests/app/test_app_shell_startup_core.py`
- `python3 -m unittest tests.exchange.test_exchange_json tests.exchange.test_repertoire_exchange_service tests.test_party_exchange_service tests.test_xml_import_service tests.test_governed_track_creation_service tests.test_authenticity_dialogs tests.test_repertoire_dialogs`
- `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.test_migration_integration tests.test_background_app_services`

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/authenticity/dialogs.py`
- `isrc_manager/constants.py`
- `isrc_manager/exchange/models.py`
- `isrc_manager/exchange/repertoire_service.py`
- `isrc_manager/exchange/repair_dialogs.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/parties/exchange_service.py`
- `isrc_manager/services/__init__.py`
- `isrc_manager/services/import_governance.py`
- `isrc_manager/services/import_repair_queue.py`
- `isrc_manager/services/imports.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/tasks/app_services.py`
- `isrc_manager/works/dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_json.py`
- `tests/exchange/test_repertoire_exchange_service.py`
- `tests/test_authenticity_dialogs.py`
- `tests/test_governed_track_creation_service.py`
- `tests/test_party_exchange_service.py`
- `tests/test_repertoire_dialogs.py`
- `tests/test_xml_import_service.py`

## Risks / Caveats

- Repertoire ZIP extraction still uses archive extraction as one coarse stage; progress is now visible and determinate, but not yet per-member granular.
- XML helper preflight failures are now queued before raising, but that helper still remains a lower-level compatibility surface rather than the preferred user-facing import route.
- The action ribbon registry still keeps `Show Add Track Panel` in its prior category; the menu organization pass did not redesign ribbon categorization.

## Explicit Outcome

New and imported tracks now always end linked to a Work before entering the live catalog.

- No live orphan Track rows are created by the governed import paths touched in this pass.
- Track-import rows that fail governance or blocking validation are persisted to a visible repair queue instead of being discarded.
- Repair replay goes back through the same governed creation seam.

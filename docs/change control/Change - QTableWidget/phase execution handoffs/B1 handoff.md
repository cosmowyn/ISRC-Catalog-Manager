# Phase B1 Handoff

## Scope executed

This pass executed **Phase B1 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved B1 scope:

- routed live header/order/hidden-column persistence on the current `QTableWidget` path through `CatalogHeaderStateManager`
- kept the existing per-profile settings namespace and legacy payload compatibility intact
- added batch-scoped validation for live header persistence behavior
- did **not** start controller, model/proxy, shell, or zoom cutover work

## What changed

### `isrc_manager/catalog_table/header_state.py`

`CatalogHeaderStateManager` gained one additional public seam needed for the live B1 cutover:

- added `restore_visibility()`
  - restores hidden-column state only
  - prefers new key-based hidden-column payloads
  - falls back to legacy label+occurrence payloads
  - falls back again to `hidden_by_default` when no visibility payload exists

Why this changed:

- the live monolith still has a bounded `_apply_saved_column_visibility()` wrapper used during header rebuild flows
- B1 needed that wrapper to delegate to the shared manager without also forcing a full order/width restore every time

### `ISRC_manager.py`

The live `QTableWidget` header-state path now delegates to the new package:

- added imports for:
  - `CatalogHeaderStateManager`
  - `CatalogColumnSpec`
- added thin App-level helpers:
  - `_catalog_header_state_manager()`
  - `_header_label_for_logical_index()`
  - `_fallback_header_column_key()`
  - `_catalog_header_column_specs()`
- updated startup/profile view-preference reads for `columns_movable` to use the manager’s loader instead of ad hoc direct settings reads
- widened `_clear_table_settings_for_path()` so reset/removal clears the new key-based payloads too:
  - `header_column_keys_json`
  - `hidden_column_keys_json`
- widened `_table_setting_keys()` so settings-bundle history captures the new key-based payloads alongside the legacy ones
- updated `_toggle_columns_movable()` so the live save path is now the manager-backed `_save_header_state()` wrapper instead of writing `columns_movable` separately
- replaced the live persistence wrappers with manager-backed implementations:
  - `_save_header_state()`
  - `_load_header_state()`
  - `_apply_saved_column_visibility()`
- updated `_load_header_state()` to silently sync the `act_reorder_columns` action with the restored live header movability state

Why this changed:

- B1’s goal is live header-state cutover while staying on the current `QTableWidget`
- the manager already had the key-based plus legacy-compatible persistence logic from A3
- the monolith now acts as a thin live adapter instead of maintaining a second independent header persistence implementation

### `tests/app/test_app_shell_catalog_header_state.py`

Added a focused B1 app-shell test module that validates the live cutover surface only:

- reuses the existing resize-history coverage for:
  - programmatic resize does not record history
  - interactive resize records one visible history entry
- adds a restart round-trip test covering:
  - column reorder persistence
  - hidden-column persistence
  - per-profile columns-movable persistence
  - refreshed column-visibility menu state
- adds a key-preference test covering:
  - `header_state` blob intentionally removed
  - conflicting legacy label payloads injected
  - key-based order restore still wins
  - key-based hidden-column restore still wins over conflicting legacy visibility payloads

## Files added

- `tests/app/test_app_shell_catalog_header_state.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/B1 handoff.md`

## Files modified

- `ISRC_manager.py`
- `isrc_manager/catalog_table/header_state.py`

## Existing files touched and why

Existing production files touched:

- `ISRC_manager.py`
  - bounded live cutover of header-state wrappers on the current widget path
- `isrc_manager/catalog_table/header_state.py`
  - added the visibility-only public seam needed by the monolith wrapper

Existing non-production file touched:

- `docs/change control/Milestones.md`
  - required append-only B1 completion record

Repository inspection stayed limited to what B1 needed:

- `docs/change control/Change - QTableWidget/Engineering plan.md`
  - source of truth for B1 scope and validation
- `docs/change control/Change - QTableWidget/phase execution handoffs/A1 handoff.md`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A2 handoff.md`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A3 handoff.md`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A4 handoff.md`
  - prior-phase context and scope boundaries
- `ISRC_manager.py`
  - current live header persistence path and related settings/history hooks
- `isrc_manager/catalog_table/header_state.py`
  - shared manager used for the live cutover
- `tests/app/_app_shell_support.py`
  - current app-shell test harness and existing resize-history cases

## How scope was kept strictly within B1

Scope discipline was enforced by keeping live changes inside header-state behavior only:

- no controller cutover
- no selection/context-menu cutover
- no `CatalogTableController` live imports
- no model/proxy live cutover
- no `CatalogTableModel` or `CatalogFilterProxyModel` runtime wiring
- no shell flip to `QTableView`
- no zoom cutover
- no monolith cleanup/removal beyond thin wrapper replacement
- no B2+ behavior pulled forward

The only live package dependency introduced in production code is the B1-approved header-state surface:

- `CatalogHeaderStateManager`
- `CatalogColumnSpec`

## What was intentionally not implemented yet

The following work remains intentionally deferred:

- B2 interaction/controller cutover
- B3 live shell flip to `QTableView` + model/proxy
- B4 remaining interaction/rendering migration work
- B5 live zoom hookup
- cleanup/removal of monolith wrappers after later cutovers

## Dormant imports, wrappers, seams, and deprecation markers

- added live imports in `ISRC_manager.py` only for the B1-approved header-state surface
- the monolith header helpers now act as thin compatibility wrappers over `CatalogHeaderStateManager`
- no controller/model/proxy/zoom dormant imports were added to production code
- no cleanup/deletion of old monolith helpers was performed
- no non-B1 deprecation markers were added

## QA checks performed

The following B1-scoped validation was run:

- `python3 -m py_compile ISRC_manager.py isrc_manager/catalog_table/header_state.py tests/app/test_app_shell_catalog_header_state.py`
  - passed
- `python3 -m unittest tests.test_catalog_table_header_zoom tests.app.test_app_shell_catalog_header_state`
  - passed
  - `10` tests total
- `python3 -m black --check isrc_manager/catalog_table/header_state.py tests/app/test_app_shell_catalog_header_state.py`
  - passed
- `python3 -m ruff check --select I001 ISRC_manager.py`
  - passed
- `python3 -m ruff check isrc_manager/catalog_table/header_state.py tests/app/test_app_shell_catalog_header_state.py`
  - passed
- dependency scan for live `catalog_table` usage outside the package
  - confirmed only `CatalogHeaderStateManager` and `CatalogColumnSpec` were introduced in production code
  - confirmed no controller/model/proxy/zoom live cutover occurred

Validation specifically covered the required B1 behaviors:

- programmatic vs interactive resize history behavior
- column reorder persistence
- column hide/show persistence
- restart round-trip
- successful key-based restore preferred over legacy fallback
- no unrelated catalog behavior cut over

## QC checks performed

- confirmed the engineering plan was read first
- confirmed B1 scope from the plan before edits
- confirmed the work remained B1-only
- confirmed only phase-appropriate files were changed
- confirmed no adjacent-phase logic was implemented early
- confirmed no worker agents were used, so there was no worker scope drift and no worker cleanup required
- confirmed the only live production dependency introduced from `isrc_manager.catalog_table` was the header-state surface needed for B1
- confirmed the current runtime still uses `QTableWidget`

## Confirmation of no adjacent-phase work

No B2+ work was performed.

Specifically not started:

- controller-based interaction routing
- double-click/context-menu/export cutover
- model/proxy runtime binding
- `QTableView` shell replacement
- live zoom routing
- monolith cleanup/removal

## Confirmation of exactly which live behavior was cut over in this phase

The following live behavior was cut over in B1:

- saving current header order/width/hidden-column state
- restoring header order/width/hidden-column state
- restoring default hidden columns when no saved visibility payload exists
- persisting and restoring per-profile columns-movable state
- keeping settings/history/reset hooks aware of the new key-based header payloads

This live cutover still runs on the existing `QTableWidget` shell.

## Confirmation that no non-B1 live behavior was cut over

The following live behavior did **not** change in B1:

- selection helpers
- double-click routing
- context-menu targeting
- selected-vs-visible export semantics
- search/filter/count/duration behavior
- shell/widget class choice
- zoom behavior

## Risks and follow-up notes for B2

- `ISRC_manager.py` now has a cleaner single source of truth for live header persistence, but the wrapper layer is intentionally still present.
  - B2 should leave those header wrappers alone unless interaction work directly needs them.
- `_catalog_header_column_specs()` now derives stable live keys for base and custom columns.
  - B2 does not need those keys yet, but B3 can build on them later.
- `_refresh_column_visibility_menu()` remains monolith-owned UI code.
  - that is intentional for B1 because only persistence was cut over
  - any broader menu/controller refactor should wait for the planned later batches
- `pyproject.toml` still uses a static setuptools package list.
  - unchanged in B1 by design
  - still worth tracking if packaged distribution must include `isrc_manager.catalog_table` before later cutovers
- full-file `black` on `ISRC_manager.py` would currently reformat unrelated pre-existing lines outside the B1 delta.
  - B1 avoided widening scope by using targeted hygiene checks instead of reformatting unrelated monolith sections

## Repo-specific conventions discovered that matter for later phases

- app-shell behavior tests are built on `tests.app._app_shell_support.AppShellTestCase`
- phase-scoped validation in this repo works best when the large monolith uses narrow hygiene checks rather than opportunistic whole-file reformatting
- settings-bundle history in the app depends on explicit key lists, so migration phases that add settings payloads must update those lists as part of the live cutover
- the app uses per-profile table settings namespaces, so live cutovers need to preserve `_table_settings_prefix()` semantics

## Ready state for next phase

Phase B1 leaves the repository ready for:

- B2 interaction/controller cutover on the current widget backend

The live app now uses `CatalogHeaderStateManager` for header persistence, while everything outside that B1 family remains on the existing monolith path.

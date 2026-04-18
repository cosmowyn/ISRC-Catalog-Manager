# Phase B2 Handoff

## Scope executed

This pass executed **Phase B2 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved B2 scope:

- routed live selection helpers through `CatalogTableController`
- routed live selected-vs-visible export scope through `CatalogTableController`
- routed live context-menu selection preservation and targeting through `CatalogTableController`
- routed live double-click and preview cell classification through `CatalogTableController`
- kept the current `QTableWidget` backend in place
- added B2-scoped validation for the required interaction behaviors
- did not start shell, model/proxy, header-state, zoom, cleanup, or B3+ work

## What changed

### `isrc_manager/catalog_table/controller.py`

`CatalogTableController` now supports the current live `QTableWidget` shell as an adapter path while preserving the existing model/proxy seams built in Phase A:

- added `CatalogCellTarget`
  - describes a clicked/view cell by row, column, track id, standard field metadata, standard media key, and custom-field metadata
  - lets live double-click and preview routing stop depending directly on `QTableWidgetItem` parsing
- added `bind_widget_seams()`
  - binds a live row-to-track-id resolver
  - binds a live hidden-row predicate for current `setRowHidden()` filtering semantics
- updated `track_id_for_index()` to fall back to the widget row resolver when no model role exists
- added `has_filtered_rows()`
  - uses proxy row counts on the future model/proxy path
  - uses hidden-row state on the current widget path
- updated selection helpers so hidden rows are skipped on the live widget path
- updated `selected_or_visible_track_ids()` to match live export semantics:
  - filtered/hidden-row state returns visible track ids
  - otherwise explicit selection is returned
  - no unfiltered/no-selection fallback to all visible rows
- added `default_conversion_track_ids()`
  - selection first
  - filtered visible rows second
  - empty otherwise
- added `prepare_context_menu_selection()`
  - preserves multi-select when right-clicking inside the current selection
  - retargets selection when right-clicking an unselected row
- widened `effective_context_menu_track_ids()` so it can accept either a `QModelIndex` or an already-resolved track id
- added `cell_target()`
  - resolves standard media columns, standard non-media columns, and custom field columns for current widget interactions

Why this changed:

- B2 needed live interaction behavior to route through the controller while the shell remains `QTableWidget`
- the controller now owns the reusable selection/targeting/routing decisions that later phases can bind to the `QTableView` model/proxy path

### `ISRC_manager.py`

The live monolith now uses the controller as a thin adapter for B2-owned behavior:

- added the live import for `CatalogTableController`
- added `_catalog_table_controller()`
  - lazily creates the controller
  - binds the current `QTableWidget`
  - binds `_track_id_for_table_row()` as the widget row identity seam
  - binds `table.isRowHidden()` as the current visible/filter seam
- replaced selection wrappers with controller delegates:
  - `_selected_track_ids()`
  - `_selected_or_visible_track_ids()`
  - `_current_visible_track_ids()`
  - `_default_conversion_track_ids()`
- updated `export_selected_to_xml()` to use `_selected_or_visible_track_ids()` instead of duplicating hidden-row and selection parsing logic
- updated `_on_item_double_clicked()` to use controller cell routing for:
  - standard non-media edit routing
  - standard media attach routing
  - custom-field edit routing
- updated `_on_table_context_menu()` to use controller context-menu selection prep and controller-backed effective target ids
- updated `_preview_blob_for_cell()` to use controller cell routing for:
  - standard media preview
  - custom blob preview
  - `Space` preview indirectly through the existing event filter path
- updated `_effective_context_menu_track_ids()` to delegate to the controller
- added the B2 deprecation markers required by the plan above replaced monolith wrappers/functions

Why this changed:

- B2 cut over only the interaction/controller family while preserving the current UI and data backend
- the App methods remain as compatibility wrappers for existing signal/action connections until the final cleanup batch

### Tests

Added focused controller tests:

- `tests/test_catalog_table_controller.py`
  - verifies live-widget selection helpers skip hidden rows
  - verifies selected-vs-visible export semantics
  - verifies default conversion scope semantics
  - verifies context-menu selection preservation and retargeting
  - verifies standard/custom/media cell route metadata

Added focused app-shell tests:

- `tests/app/test_app_shell_catalog_controller.py`
  - validates right-click inside selection preserves multi-select
  - validates selected-vs-visible export scope
  - validates default conversion scope
  - validates double-click standard edit path
  - validates double-click standard media path
  - reuses existing custom text-field double-click coverage
  - validates `Space` preview routing on the current cell

Extended the shared app-shell harness:

- `tests/app/_app_shell_support.py`
  - added B2 case methods used by the new app-shell test module
  - imported `QKeyEvent` for the direct `Space` preview event validation

## Files added

- `tests/test_catalog_table_controller.py`
- `tests/app/test_app_shell_catalog_controller.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/B2 handoff.md`

## Files modified

- `ISRC_manager.py`
- `isrc_manager/catalog_table/controller.py`
- `tests/app/_app_shell_support.py`
- `docs/change control/Milestones.md`

## Existing files touched and why

Existing production files touched:

- `ISRC_manager.py`
  - bounded live cutover of B2 interaction, selection, preview, and export-scope wrappers on the current widget path
- `isrc_manager/catalog_table/controller.py`
  - added the live-widget controller seams needed for B2 without introducing model/proxy runtime binding

Existing non-production files touched:

- `tests/app/_app_shell_support.py`
  - added B2 app-shell validation cases
- `docs/change control/Milestones.md`
  - required append-only B2 completion record

Repository inspection stayed limited to what B2 needed:

- prior phase handoffs in `docs/change control/Change - QTableWidget/phase execution handoffs/`
- `docs/change control/Change - QTableWidget/Engineering plan.md`
- the B2 prompt
- controller code
- live selection/context-menu/double-click/preview/export call sites in `ISRC_manager.py`
- existing app-shell support cases and test module patterns

## How scope was kept strictly within B2

Scope discipline was enforced by keeping live changes inside the B2 behavior family only:

- no shell flip
- no `QTableView` construction for the catalog table
- no `CatalogTableModel` live binding
- no `CatalogFilterProxyModel` live binding
- no refresh/filter/sort/count/duration migration
- no header-state changes beyond leaving B1 wrappers intact
- no zoom cutover
- no final cleanup/removal
- no B3+ behavior implemented early

The live catalog shell remains `QTableWidget`:

- `isrc_manager/main_window_shell.py` still creates `app.table = QTableWidget()`
- scope scan found no production `CatalogTableModel` or `CatalogFilterProxyModel` references in `ISRC_manager.py` or `isrc_manager/main_window_shell.py`
- `CatalogTableController` is the only new B2 production dependency from `isrc_manager.catalog_table`

## What was intentionally not implemented yet

The following work remains intentionally deferred:

- B3 live shell flip to `QTableView`
- live `CatalogTableModel` and `CatalogFilterProxyModel` binding
- catalog refresh/population/filter/sort/count/duration migration
- B4 badge/icon and proxy-semantic parity work
- B5 live zoom hookup
- final cleanup/removal of monolith wrappers and row-item helpers
- removal of `_track_id_for_table_row()` and other `QTableWidgetItem` identity fallbacks

## Dormant imports, wrappers, seams, and deprecation markers

- added live `CatalogTableController` import in `ISRC_manager.py`
- added `_catalog_table_controller()` as the live widget adapter seam
- kept App-level methods as thin compatibility wrappers for existing signals/actions
- added B2 deprecation markers above:
  - `_selected_track_ids`
  - `_selected_or_visible_track_ids`
  - `_default_conversion_track_ids`
  - `_current_visible_track_ids`
  - `_on_item_double_clicked`
  - `_on_table_context_menu`
  - `_preview_blob_for_cell`
  - `_effective_context_menu_track_ids`
- no runtime warnings were added
- no wrapper removal was performed

## QA checks performed

The following B2-scoped validation was run:

- `python3 -m py_compile ISRC_manager.py isrc_manager/catalog_table/controller.py tests/test_catalog_table_controller.py tests/app/test_app_shell_catalog_controller.py tests/app/_app_shell_support.py`
  - passed
- `python3 -m unittest tests.test_catalog_table_controller tests.app.test_app_shell_catalog_controller`
  - passed
  - `10` tests total
- `python3 -m unittest tests.test_catalog_table_models tests.test_catalog_table_header_zoom tests.test_catalog_table_controller`
  - passed
  - `16` tests total
- `python3 -m unittest tests.app.test_app_shell_catalog_header_state tests.app.test_app_shell_catalog_controller`
  - passed
  - `11` tests total
- `python3 -m black --check isrc_manager/catalog_table/controller.py tests/test_catalog_table_controller.py tests/app/test_app_shell_catalog_controller.py tests/app/_app_shell_support.py`
  - passed
- `python3 -m ruff check isrc_manager/catalog_table/controller.py tests/test_catalog_table_controller.py tests/app/test_app_shell_catalog_controller.py tests/app/_app_shell_support.py`
  - passed
- `python3 -m ruff check --select I001 ISRC_manager.py`
  - passed
- `git diff --check`
  - passed

Validation specifically covered the required B2 behaviors:

- right-click inside selection preserves multi-select
- double-click standard non-media edit path
- double-click standard media attach path
- double-click custom field edit path
- selected-vs-visible export semantics
- default conversion selected-vs-filtered-visible semantics
- `Space` preview routing from the current cell
- no shell/backend swap yet

## QC checks performed

- confirmed the engineering plan was read first
- confirmed B2 scope from the plan before edits
- confirmed prior handoffs were read before execution
- confirmed the work remained B2-only
- confirmed only phase-appropriate files and behaviors were changed
- confirmed no adjacent-phase logic was implemented early
- confirmed no worker agents were used, so there was no worker scope drift and no idle worker cleanup required
- confirmed no model/proxy production wiring was introduced
- confirmed no shell replacement was introduced
- confirmed no zoom or header-state behavior was changed in B2
- confirmed no cleanup/removal was performed

## Confirmation of no adjacent-phase work

No B3+ work was performed.

Specifically not started:

- `QTableView` shell replacement
- `CatalogTableModel` runtime binding
- `CatalogFilterProxyModel` runtime binding
- refresh/filter/sort/count/duration migration
- badge/icon proxy parity migration
- live zoom routing
- monolith cleanup/removal

## Confirmation of exactly which live behavior was cut over in this phase

The following live behavior was cut over in B2:

- catalog selection id resolution
- selected-vs-visible export scope
- default conversion track scope
- visible-row track ordering for preview/export helpers
- context-menu selection preservation
- context-menu effective target ids
- double-click standard/custom/media routing
- cell preview standard/custom routing
- `Space` preview path through the controller-backed preview wrapper

This live cutover still runs on the existing `QTableWidget` shell.

## Confirmation that no non-B2 live behavior was cut over

The following live behavior did **not** change in B2:

- shell/widget class choice
- catalog population
- search/filter implementation
- sort implementation
- count/duration labels
- model/proxy runtime ownership
- header-state persistence
- zoom behavior
- badge/icon rendering behavior

## Risks and follow-up notes for B3

- `_track_id_for_table_row()` remains the live row identity resolver for the current widget seam.
  - B3/B4 should retire that dependency when track identity comes from model roles end-to-end.
- Context-menu action construction still uses some existing item/header lookups after the B2 target ids are resolved.
  - B2 intentionally cut over targeting only.
  - stable column-key action construction belongs with later model/proxy and badge/proxy parity work.
- `export_selected_to_xml()` now shares the controller-backed selected-vs-visible scope helper.
  - this reduces duplicate hidden-row parsing before B3.
- Full-file `black` on `ISRC_manager.py` remains intentionally avoided because the monolith still has unrelated pre-existing formatting churn outside the B2 delta.
  - targeted checks were used instead, matching the B1 convention.
- `pyproject.toml` still uses a static setuptools package list.
  - unchanged in B2 by design
  - still worth tracking if packaged distribution must include `isrc_manager.catalog_table` before later cutovers

## Repo-specific conventions discovered that matter for later phases

- app-shell behavior tests should continue to use `tests.app._app_shell_support.AppShellTestCase`
- phase-scoped test modules keep the migration reviewable without re-running unrelated app-shell suites by default
- the monolith is better handled with targeted hygiene checks until final cleanup/reformat phases
- live settings/history wrappers should remain explicit and narrow, as seen in B1 and preserved in B2

## Ready state for next phase

Phase B2 leaves the repository ready for:

- B3 live shell flip to `QTableView` + model/proxy, when explicitly requested

The live app now uses `CatalogTableController` for B2 interaction and selection responsibilities while everything outside that behavior family remains on the existing `QTableWidget` monolith path.

# Phase A3 Handoff

## Scope executed

This pass executed **Phase A3 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved A3 scope:

- implemented `header_state.py`, `controller.py`, and `zoom.py` with real logic
- kept the new logic runtime-dormant with no production cutover
- added focused unit tests only for the A3-required areas:
  - header-state compatibility helpers
  - zoom state machine and throttle behavior
- did **not** perform A4 or any Phase B work

## What changed

### `isrc_manager/catalog_table/header_state.py`

`CatalogHeaderStateManager` moved from placeholder methods to a real pure persistence layer:

- added stable setting-key constants for:
  - native header state
  - legacy label order payloads
  - new key-based column order payloads
  - legacy hidden-column payloads
  - new key-based hidden-column payloads
  - columns-movable state
- added configurable settings-prefix support through:
  - `settings_prefix()`
  - `set_settings_prefix()`
  - `settings_key()`
- implemented `save_state()` to write:
  - native `QHeaderView.saveState()`
  - legacy visual label order
  - new key-based visual order
  - legacy hidden-column payload
  - new key-based hidden-column payload
  - `columns_movable`
- implemented `restore_state()` with the intended compatibility strategy:
  - prefer key-based restore inputs
  - use native `restoreState()` only when the saved/current structure is compatible
  - fall back to deterministic custom reordering when native restore is unsafe or unavailable
  - fall back again to legacy label+occurrence tokens when key-based payloads do not exist
  - apply `hidden_by_default` when no persisted visibility state exists
- added pure helper seams for later B1 wiring:
  - `load_columns_movable_state()`
  - `load_column_key_order()`
  - `load_hidden_column_keys()`
  - `load_legacy_header_labels()`
  - `load_legacy_hidden_columns()`

### `isrc_manager/catalog_table/controller.py`

`CatalogTableController` moved from placeholder methods to a real dormant controller seam:

- added explicit model/view binding helpers:
  - `bind_view()`
  - `bind_models()`
  - `source_model()`
  - `proxy_model()`
  - `active_model()`
- implemented proxy/source mapping helpers:
  - `map_to_source()`
  - `map_from_source()`
  - `source_index_for_track_id()`
  - `view_index_for_track_id()`
  - `track_id_for_index()`
  - `track_id_for_source_row()`
  - `source_row_for_track_id()`
- implemented selection and scope helpers:
  - `current_track_id()`
  - `selected_track_ids()`
  - `visible_track_ids()`
  - `selected_or_visible_track_ids()`
  - `effective_context_menu_track_ids()`
- kept the controller dormant by not wiring it into any production runtime path

### `isrc_manager/catalog_table/zoom.py`

`CatalogZoomController` moved from a minimal placeholder to a real pure zoom state machine:

- added signals:
  - `zoom_percent_changed`
  - `zoom_applied`
- added throttled apply behavior via an internal single-shot `QTimer`
- implemented a stable zoom source of truth with the planned constants:
  - default `100`
  - min `80`
  - max `160`
  - step `5`
- added real public behavior for:
  - `bind_view()`
  - `set_apply_callback()`
  - `zoom_percent()`
  - `pending_zoom_percent()`
  - `has_pending_apply()`
  - `throttle_ms()`
  - `set_throttle_ms()`
  - `set_zoom_percent()`
  - `step_zoom()`
  - `apply_pinch_scale()`
  - `reset_zoom()`
  - `flush_pending_apply()`
  - `layout_state()`
  - `restore_layout_state()`
  - `on_profile_changed()`
  - `normalize_zoom_percent()`
- kept the controller dormant by default:
  - no live UI was bound
  - no view mutation occurs unless an explicit apply callback is supplied later

## Files added

- `tests/test_catalog_table_header_zoom.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A3 handoff.md`

## Files modified

- `isrc_manager/catalog_table/header_state.py`
- `isrc_manager/catalog_table/controller.py`
- `isrc_manager/catalog_table/zoom.py`

## Existing files touched and why

No existing production runtime files outside the new package were modified.

Existing non-production files touched:

- `docs/change control/Milestones.md`
  - required append-only A3 completion record

Repository inspection stayed limited to what A3 needed:

- `docs/change control/Change - QTableWidget/Engineering plan.md`
  - source of truth for A3 scope and sequencing
- `docs/change control/Change - QTableWidget/phase execution handoffs/A1 handoff.md`
  - prior-phase scaffolding context
- `docs/change control/Change - QTableWidget/phase execution handoffs/A2 handoff.md`
  - prior-phase model/proxy context
- `ISRC_manager.py`
  - limited inspection of current header persistence and selection/context semantics
- `isrc_manager/contract_templates/dialogs.py`
  - existing repository pattern for zoom-state/timer behavior
- `tests/qt_test_helpers.py`
  - current headless Qt test conventions
- `Makefile`
  - local validation command conventions

## How scope was kept strictly within A3

Scope discipline was enforced by keeping all implementation inside the A3-approved module set:

- no changes to `models.py`
- no changes to `table_model.py`
- no changes to `filter_proxy.py`
- no changes to `ISRC_manager.py`
- no shell flip
- no live runtime imports or dependencies were introduced outside dormant package scaffolding
- no header-state cutover
- no controller/interaction cutover
- no zoom UI cutover
- no production behavior changes
- no A4 or Phase B work

The only non-package addition was the focused A3 test module that the prompt explicitly allowed.

## What was intentionally not implemented yet

The following work remains intentionally unimplemented for later phases:

- A4 structural audit work
- live header-state routing from the monolith to `CatalogHeaderStateManager`
- live interaction routing to `CatalogTableController`
- live zoom UI hookup and layout integration to `CatalogZoomController`
- any `QTableView` shell cutover
- any monolith deprecation markers
- any Phase B live behavior migration

## Dormant imports, wrappers, seams, and deprecation markers

- no production dormant imports were added outside the package
- no runtime wrappers were added outside the pure package seam
- no deprecation markers were added to monolith code

The only dormant seam added is the real-but-unwired implementation inside the new package itself.

## QA checks performed

The following phase-scoped validation was run:

- `python3 -m py_compile isrc_manager/catalog_table/header_state.py isrc_manager/catalog_table/controller.py isrc_manager/catalog_table/zoom.py tests/test_catalog_table_header_zoom.py`
  - passed
- `python3 -m unittest tests.test_catalog_table_header_zoom`
  - passed
- `python3 -m black --check isrc_manager/catalog_table/header_state.py isrc_manager/catalog_table/controller.py isrc_manager/catalog_table/zoom.py tests/test_catalog_table_header_zoom.py`
  - passed
- `python3 -m ruff check isrc_manager/catalog_table/header_state.py isrc_manager/catalog_table/controller.py isrc_manager/catalog_table/zoom.py tests/test_catalog_table_header_zoom.py`
  - passed
- dependency scan for imports/usage of the new A3 units outside `isrc_manager/catalog_table/`
  - no results

Validation specifically covered the required A3 behaviors:

- header-state compatibility helpers
- zoom state machine
- zoom throttle coalescing

## QC checks performed

- confirmed the engineering plan was read first
- confirmed the work remained A3-only
- confirmed only phase-appropriate implementation files were changed in production code
- confirmed the only non-production addition was the focused A3 test module
- confirmed no adjacent-phase logic was implemented early
- confirmed no production path depends on these modules yet beyond dormant scaffolding
- confirmed no shell/UI/runtime wiring was introduced
- confirmed no worker agents were used, so there was no worker scope drift and no worker cleanup required

## Confirmation of no adjacent-phase work

No A4 or Phase B work was performed.

Specifically not started:

- structural audit gate work
- header-state cutover
- controller/interaction cutover
- zoom UI cutover
- live shell flip
- monolith cleanup
- deprecation marking

## Confirmation of live behavior status

Live behavior was **not** cut over.

The production application still uses the existing monolith/header/widget path. The A3 units remain standalone and dormant until a later cutover phase binds them into the live runtime.

## Risks and follow-up notes for A4/B1

- `CatalogHeaderStateManager` now writes new key-based payloads alongside legacy label-based payloads.
  - A4 should verify the surface is coherent and ready.
  - B1 can route live persistence through this manager without redesigning the payload format.
- `CatalogHeaderStateManager.restore_state()` temporarily enables section movement during restore so custom visual-order application remains deterministic even when the saved final state is non-movable.
  - That behavior is intentional and should be preserved during B1 integration.
- `CatalogTableController` now has real mapping/selection helpers, but it was not wired into live interaction flows.
  - B1 does not use it yet.
  - B2 can build on the now-real dormant seam.
- `CatalogZoomController` now has throttled apply and layout-state seams, but no live view callback is bound yet.
  - B5 can attach the actual visual-apply path later.
- `pyproject.toml` still uses a static setuptools package list.
  - unchanged in A3 by design
  - still worth tracking if packaged distribution must include the new package before live cutover

## Repo-specific conventions discovered that matter for later phases

- headless Qt tests use `tests.qt_test_helpers.require_qapplication()`, `pump_events()`, and `wait_for()`
- repository zoom/state logic often uses explicit `QTimer`-backed state machines rather than implicit UI behavior
- `unittest` remains the expected test framework
- `black` and `ruff` are part of the normal validation bar
- `QSettings` INI-backed tests are already a common repository pattern and are safe for pure persistence helpers

## Ready state for next phase

Phase A3 leaves the repository ready for:

- A4 structural audit of the now-real external catalog-table module surface
- B1 live header-state cutover onto `CatalogHeaderStateManager`

No production cutover work has been pulled forward.

# Phase A2 Handoff

## Scope executed

This pass executed **Phase A2 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved A2 scope:

- implemented `models.py`, `table_model.py`, and `filter_proxy.py` as standalone pure units
- added focused unit tests for roles, sorting, search, and explicit track filtering
- kept the work runtime-dormant with no production wiring
- did **not** implement header-state, controller, zoom, shell cutover, or any Phase B behavior

## What changed

### `isrc_manager/catalog_table/models.py`

`models.py` moved from scaffolding to a real pure data layer:

- kept the planned role constants:
  - `SortRole`
  - `SearchTextRole`
  - `TrackIdRole`
  - `ColumnKeyRole`
  - `RawValueRole`
- added stable normalization helpers:
  - `_coerce_text()`
  - `natural_sort_key()`
  - `comparison_sort_key()`
- implemented `CatalogColumnSpec` normalization and validation:
  - non-empty `key`
  - non-empty `header_text`
  - normalized legacy labels
  - `all_header_labels` convenience property
- implemented `CatalogCellValue` normalization:
  - stable `display_text`
  - defaulted `search_text`
  - defaulted `raw_value`
  - defaulted `sort_value`
  - normalized tooltip/alignment/decoration payloads
- added `CatalogCellValue.from_value()` for safe pure snapshot construction
- implemented `CatalogRowSnapshot` normalization:
  - coerces simple raw values into `CatalogCellValue`
  - validates non-empty column keys
  - normalizes `track_id`
- implemented `CatalogSnapshot` normalization and validation:
  - tuple-normalized column specs
  - tuple-normalized rows
  - dict-normalized metadata
  - unique column-key enforcement
  - unique track-id enforcement
  - `column_index()` and `column_spec()` lookup helpers

### `isrc_manager/catalog_table/table_model.py`

`CatalogTableModel` now exposes real pure model behavior:

- `data()` now returns role-backed values for:
  - `DisplayRole`
  - `EditRole`
  - `ToolTipRole`
  - `DecorationRole`
  - `TextAlignmentRole`
  - `SortRole`
  - `SearchTextRole`
  - `TrackIdRole`
  - `ColumnKeyRole`
  - `RawValueRole`
- `headerData()` now returns:
  - header display text
  - header tooltip from `CatalogColumnSpec.notes`
  - stable column key through `ColumnKeyRole`
- `set_snapshot()` now resets the model and refreshes track-id lookup state
- `roleNames()` now exposes the custom roles explicitly for auditability and later model/view work

### `isrc_manager/catalog_table/filter_proxy.py`

`CatalogFilterProxyModel` now owns real pure search/sort/filter behavior:

- stores normalized search text and explicit search-column key
- stores explicit track-id filters as a normalized frozen set
- sets `SortRole` as the proxy sort role
- `filterAcceptsRow()` now applies:
  - explicit track-id filtering
  - search text filtering
  - all-searchable-column search
  - single-column search keyed by stable column key
- `lessThan()` now sorts by:
  - precomputed `SortRole` payload
  - natural text fallback
  - stable track-id / row fallback for deterministic ordering
- search-all mode respects `CatalogColumnSpec.searchable`
- explicit search-column mode resolves via stable `ColumnKeyRole`

### Focused tests added

`tests/test_catalog_table_models.py` was added to cover the A2 validation requirements:

- snapshot validation for duplicate column keys and track ids
- model role exposure and header metadata
- `CatalogTableModel.data()` purity / side-effect safety for precomputed payloads
- model snapshot reset and track-id mapping
- proxy natural sorting
- proxy sort-role numeric sorting
- proxy search across searchable columns only
- proxy explicit single-column search by stable column key
- proxy explicit track filtering, including combination with search text

## Files added

- `tests/test_catalog_table_models.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/A2 handoff.md`

## Files modified

- `isrc_manager/catalog_table/models.py`
- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/catalog_table/filter_proxy.py`

## Existing files touched and why

No existing production runtime files outside the new package were modified.

Existing non-production files touched:

- `docs/change control/Milestones.md`
  - required append-only A2 completion record

Repository inspection stayed limited to what A2 needed:

- `docs/change control/Change - QTableWidget/Engineering plan.md`
  - source of truth for phase scope
- `ISRC_manager.py`
  - limited inspection of current sort/search semantics for parity targeting
- `tests/qt_test_helpers.py`
  - current headless Qt test convention
- `Makefile`
  - local validation command convention
- `docs/change control/Change - QTableWidget/phase execution handoffs/A1 handoff.md`
  - prior-phase context and repository notes

## How scope was kept strictly within A2

Scope discipline was enforced by keeping all implementation inside the A2-approved pure units:

- no changes to `header_state.py`
- no changes to `controller.py`
- no changes to `zoom.py`
- no changes to `__init__.py`
- no changes to `ISRC_manager.py`
- no shell or UI wiring
- no runtime dependency introduced from production code to `isrc_manager.catalog_table`
- no header/controller/zoom cutover logic
- no `QTableView` shell flip
- no monolith deprecation markers
- no behavior changes in live production code

The only non-package code addition was the focused A2 test module, which was explicitly allowed by the prompt.

## What was intentionally not implemented yet

The following work remains intentionally unimplemented for later phases:

- header-state save/restore compatibility logic
- controller selection/context-menu/double-click/export logic
- zoom state machine, UI hooks, and persistence
- any production runtime use of `CatalogTableModel` or `CatalogFilterProxyModel`
- live shell cutover from `QTableWidget` to `QTableView`
- badge/icon parity work beyond carrying inert role payloads
- any Phase A3, A4, or Phase B work

## Dormant imports, wrappers, seams, and deprecation markers

- no production dormant imports were added
- no runtime wrappers or compatibility seams were added outside the pure units themselves
- no deprecation markers were added to monolith code

The pure model/proxy package remains runtime-dormant because nothing outside `isrc_manager/catalog_table/` imports or uses it yet.

## QA checks performed

The following phase-scoped validation was run:

- `python3 -m py_compile isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/filter_proxy.py tests/test_catalog_table_models.py`
  - passed
- `python3 -m unittest tests.test_catalog_table_models`
  - passed
- `python3 -m black --check isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/filter_proxy.py tests/test_catalog_table_models.py`
  - passed
- `python3 -m ruff check isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/filter_proxy.py tests/test_catalog_table_models.py`
  - passed
- dependency scan for imports/usage of the new package and A2 symbols outside `isrc_manager/catalog_table/`
  - no results

Validation specifically covered the required A2 behaviors:

- roles
- sorting
- search
- explicit track filtering
- `CatalogTableModel.data()` purity / precomputed-payload behavior

## QC checks performed

- confirmed the engineering plan was read first
- confirmed the work remained A2-only
- confirmed only phase-appropriate implementation files were changed in production code
- confirmed the only non-production addition was a focused A2 test module
- confirmed no adjacent-phase logic was implemented early
- confirmed no production path depends on these modules yet
- confirmed no shell/UI/runtime wiring was introduced
- confirmed no worker agents were used, so there was no worker scope drift and no worker cleanup required

## Confirmation of no adjacent-phase work

No A3, A4, or Phase B work was performed.

Specifically not started:

- header-state implementation
- controller implementation
- zoom implementation
- live cutover
- monolith cleanup
- deprecation marking

## Confirmation of live behavior status

Live behavior was **not** cut over.

The production application still uses the existing `QTableWidget` path. The A2 model/proxy units remain standalone and test-only at this stage.

## Risks and follow-up notes for A3/A4

- `CatalogCellValue.decoration_key` is still a passive payload field.
  - A2 intentionally avoids pulling icon/materialization behavior forward.
  - If A3 or later needs richer decoration payloads, that can be refined without touching production wiring yet.
- `CatalogFilterProxyModel` currently falls back from an unresolved search-column key to all searchable columns.
  - This is resilient for stale search-column state, but A3/A4 can revisit whether stricter invalid-key handling is preferable.
- `CatalogSnapshot` now enforces unique track ids and unique column keys.
  - Later phases can rely on that invariant for controller/header work.
- `CatalogTableModel.roleNames()` now makes the custom roles explicit.
  - This should help future audit/debug work when the live cutover begins.
- the repository still uses a static setuptools package list in `pyproject.toml`
  - unchanged in A2 by design
  - still worth tracking for later packaging/distribution work if the new package must ship before cutover

## Repo-specific conventions discovered that matter for later phases

- headless Qt tests use `tests.qt_test_helpers.require_qapplication()`
- the test suite is built on `unittest`, not `pytest`
- local hygiene expectations align with `black` and `ruff`
- custom Qt data roles are acceptable and auditable in this codebase when clearly named
- repository style favors explicit, typed, importable units with narrow responsibilities

## Ready state for next phase

Phase A2 leaves the repository ready for:

- A3 implementation of `header_state.py`, `controller.py`, and `zoom.py` as pure standalone units without live wiring
- A4 structural review of the now-real pure catalog table module surface

No production cutover work has been pulled forward.

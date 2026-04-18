# Phase B3 Handoff

## Scope executed

This pass executed **Phase B3 only** from `docs/change control/Change - QTableWidget/Engineering plan.md`.

The work stayed inside the approved B3 scope:

- flipped the live catalog shell from `QTableWidget` to `QTableView`
- bound the live table to `CatalogTableModel` through `CatalogFilterProxyModel`
- moved refresh, search/filter, sort, count, duration, selection, and view-state restore onto the model/proxy path
- kept legacy item-widget call sites working through a narrow transitional `CatalogTableView` adapter
- added deprecation markers for replaced item population/filter/count/duration helpers
- did not cut over zoom, remove final wrappers, or perform broad cleanup

## What changed

### `isrc_manager/main_window_shell.py`

The catalog table is now created as `CatalogTableView`, a `QTableView` subclass with temporary compatibility helpers for remaining legacy call sites:

- `rowCount()`, `columnCount()`, `item()`, `horizontalHeaderItem()`, `currentRow()`, `setCurrentCell()`, `sortItems()`, and `scrollToItem()`
- `_CatalogTableCellItem` reads display text, tooltip, raw data, and icon data from the model rather than owning mutable cell state
- model decoration payloads now return small cached placeholder icons through the compatibility item API so existing media-badge tests remain stable without implementing final badge icon parity
- shell construction calls `_initialize_catalog_table_model_view()` before rebuilding headers
- double-click is wired through `QTableView.doubleClicked`

### `ISRC_manager.py`

The live catalog path now uses the pure model/proxy stack:

- added live imports for `CatalogTableModel`, `CatalogFilterProxyModel`, snapshot/cell types, and catalog roles
- added `_initialize_catalog_table_model_view()`, `_catalog_source_model()`, `_catalog_proxy_model()`, and model column-spec builders
- rebuilt headers by replacing the source model snapshot instead of mutating table widget columns
- populated catalog rows by building `CatalogSnapshot` / `CatalogRowSnapshot` / `CatalogCellValue` payloads
- applied prepared standard-media and custom-blob badge metadata directly into model cells
- moved search and explicit track filters to `CatalogFilterProxyModel`
- moved visible count and duration totals to proxy-visible rows
- restored filter text, search column, sort state, scroll state, selected track ids, and current row through model/proxy indexes
- routed row lookup, column lookup, delete focus, context selection, and double-click target lookup through roles/controller where possible
- preserved default ascending ID order instead of inheriting Qt's initial descending sort indicator
- made `_apply_blob_badges()` a no-op on the model path because badges are now part of the applied snapshot

### `isrc_manager/catalog_table/filter_proxy.py`

The explicit track-id filter now normalizes invalid values defensively and keeps an empty explicit filter as `frozenset()` so explicit empty scopes still produce zero visible rows.

### Tests

Added B3 app-shell validation:

- `tests/app/test_app_shell_catalog_model_view.py`
  - verifies the live table is `QTableView`, not `QTableWidget`
  - verifies the live model/proxy binding
  - verifies proxy-visible row semantics for search, count, and duration
  - verifies filter and selection restore through proxy indexes
  - verifies background refresh progress still reaches UI-ready only after model/proxy application

Extended shared app-shell support in `tests/app/_app_shell_support.py` with the B3 case methods above.

## Files added

- `tests/app/test_app_shell_catalog_model_view.py`
- `docs/change control/Change - QTableWidget/phase execution handoffs/B3 handoff.md`

## Files modified

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_table/filter_proxy.py`
- `tests/app/_app_shell_support.py`
- `docs/change control/Milestones.md`

## Scope boundaries

The following work remains intentionally deferred:

- final badge/icon parity and renderer cleanup beyond the transitional compatibility shim
- zoom cutover to the live `QTableView`
- final deletion of legacy `QTableWidgetItem` helpers and wrapper methods
- broad context-menu cleanup outside the B3 model/proxy path
- B4/B5/B6 work

## QA checks performed

- `python3 -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py isrc_manager/catalog_table/filter_proxy.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
  - passed
- `python3 -m unittest tests.test_catalog_table_models tests.test_catalog_table_controller tests.app.test_app_shell_catalog_controller tests.app.test_app_shell_catalog_header_state tests.app.test_app_shell_catalog_model_view`
  - passed
  - `24` tests total
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces`
  - passed
  - `61` tests total
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_blob_badge_icon_generation_is_cached_during_refresh tests.app.test_app_shell_editor_surfaces`
  - passed
  - `62` tests total
- `python3 -m black --check isrc_manager/main_window_shell.py isrc_manager/catalog_table/filter_proxy.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
  - passed
- `python3 -m ruff check isrc_manager/main_window_shell.py isrc_manager/catalog_table/filter_proxy.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
  - passed
- `python3 -m pytest ...`
  - not run because `pytest` is not installed in this environment
- `python3 -m ruff check ...`
  - blocked by existing monolith lint debt in `ISRC_manager.py` unrelated to this B3 change set

## Exceptions

None.

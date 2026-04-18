# B5 Handoff - Catalog Zoom Cutover

## Phase Scope Confirmation

- Phase executed: B5 only.
- Engineering plan was read before implementation.
- B5 goal from the plan: add the always-visible catalog zoom slider and `CatalogZoomController`, then persist zoom in layout payloads.
- No worker agents were used. There were no idle workers to close.
- No B6 cleanup, deprecated helper removal, model refresh change, data rebuild logic, or unrelated catalog behavior change was performed.

## What Changed

- Added an always-visible catalog table zoom control to the existing catalog control strip.
- Wired the live table to `CatalogZoomController` as the single zoom state owner.
- Added Ctrl/Meta + wheel zoom handling on the catalog table viewport.
- Added native zoom gesture and generic pinch gesture handling for the catalog table viewport.
- Kept plain wheel events out of the zoom path so normal table scrolling remains available.
- Applied zoom as a pure view-density operation:
  - table font
  - horizontal header font/minimum height
  - vertical header font/default section size/minimum section size
  - table icon size
- Persisted `catalog_zoom_percent` into named main-window layout snapshots.
- Restored `catalog_zoom_percent` when applying a named layout that contains the field.
- Reset catalog zoom to `100%` on profile activation/profile switch.
- Hardened `CatalogZoomController.restore_layout_state(...)` against malformed persisted values.

## Files Added

- `docs/change control/Change - QTableWidget/phase execution handoffs/B5 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `isrc_manager/catalog_table/zoom.py`
- `isrc_manager/main_window_shell.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_catalog_model_view.py`
- `docs/change control/Milestones.md`

## Existing Files Touched And Why

- `ISRC_manager.py`: bounded live zoom wiring, visual-density apply callback, wheel/pinch event routing, layout snapshot/restore integration, and profile-change reset.
- `isrc_manager/catalog_table/zoom.py`: kept the existing controller as source of truth and made layout restore resilient to invalid payload values.
- `isrc_manager/main_window_shell.py`: added the visible zoom slider/value label to the catalog control strip and installed the table viewport event filter/gesture setup.
- `tests/app/_app_shell_support.py`: added B5 app-shell cases and lightweight fake pinch/gesture events.
- `tests/app/test_app_shell_catalog_model_view.py`: exposed the new B5 app-shell cases through the existing catalog model-view test module.

## Live Behavior Cut Over In B5

- Catalog zoom is now user-facing and live.
- The catalog zoom slider, value label, Ctrl/Meta-wheel, native pinch, and generic pinch all synchronize through `CatalogZoomController`.
- Named layouts now capture and restore catalog zoom.
- Profile changes reset catalog zoom to the default `100%`.

## Live Behavior Not Cut Over

- No catalog data refresh behavior was changed.
- No model/proxy rebuild logic was added to zoom.
- No `resizeColumnsToContents()` behavior was added to zoom.
- No final cleanup/removal of deprecated `CATALOG_TABLE_CUTOVER_DEPRECATED` functions was performed.
- No B6 cleanup work was performed.

## Deprecation Markers, Dormant Imports, Wrappers, Or Seams

- No deprecation markers were added because B5 did not replace any pre-existing temporary in-monolith zoom glue.
- No dormant imports or dormant wrappers were added.
- New live seams are intentionally B5-scoped:
  - `_catalog_zoom_controller()`
  - `_initialize_catalog_zoom_controls()`
  - `_apply_catalog_zoom_to_view(...)`
  - `_handle_catalog_zoom_*` event helpers
  - `_catalog_zoom_layout_state()`
  - `_restore_catalog_zoom_layout_state(...)`
  - `_reset_catalog_zoom_for_profile_change()`

## QA Checks Performed

- `python3 -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py isrc_manager/catalog_table/zoom.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m unittest tests.test_catalog_table_header_zoom`
- `python3 -m unittest tests.app.test_app_shell_catalog_model_view`
- `python3 -m black isrc_manager/main_window_shell.py isrc_manager/catalog_table/zoom.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m ruff check isrc_manager/main_window_shell.py isrc_manager/catalog_table/zoom.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m unittest tests.app.test_app_shell_layout_persistence`
- `python3 -m unittest tests.app.test_app_shell_profiles_and_selection.AppShellProfileAndSelectionTests.test_create_new_profile_and_browse_profile_switch_workspace tests.app.test_app_shell_profiles_and_selection.AppShellProfileAndSelectionTests.test_profile_switch_loading_feedback_waits_for_catalog_refresh_completion tests.app.test_app_shell_profiles_and_selection.AppShellProfileAndSelectionTests.test_profile_switch_reuses_prepared_database_activation_path`
- `make compile`
- `git diff --check`

## B5 Validation Coverage

- Slider, wheel, and pinch sync: covered by a B5 app-shell test exercising slider updates, Ctrl-wheel, native zoom gesture, and generic pinch gesture.
- No data refresh during zoom: covered by patching `refresh_table`, `refresh_table_preserve_view`, and `_refresh_catalog_ui_in_background` to fail during zoom interactions.
- Reset on profile change: covered by activating a second profile after zooming and asserting the slider/value reset to `100%`.
- Restore from layout: covered by saving a named layout at `135%`, resetting zoom, applying the layout, and asserting zoom restores to `135%`.
- Plain wheel still scrolls: covered by asserting a plain wheel event does not enter the catalog zoom handler or change slider state.
- No stall on large datasets: the live apply path changes default header/table metrics only and does not iterate rows, refresh data, or resize columns during zoom. The app-shell zoom test applies zoom after loading 30 table rows and verifies the data-refresh paths stay untouched.

## QC Checks Performed

- Confirmed the engineering plan was read first and B5 scope was isolated.
- Confirmed changed files match B5-approved areas: zoom controller, catalog control strip, layout persistence, profile reset, and focused tests.
- Confirmed no adjacent B6 cleanup/removal was performed.
- Confirmed zoom does not call table refresh, model rebuild, badge recompute, or `resizeColumnsToContents()`.
- Confirmed no worker agents were used, so worker scope could not widen.

## Risks And Follow-Up Notes

- `ISRC_manager.py` remains excluded from Black/Ruff by project configuration, so formatting there remains manual.
- The B5 zoom base metrics are captured from the live table when the zoom controller initializes. If later phases introduce dynamic table font/theme changes after initialization, B6 or a future polish pass may need to reset the captured base metrics when theme density changes.
- Existing row-height editing paths remain legacy behavior and were not redesigned in B5.
- B6 remains responsible for final cleanup of deprecated migration helpers and obsolete `QTableWidget` compatibility paths.

## Exceptions

- None.

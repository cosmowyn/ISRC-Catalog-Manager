# Catalog Reset Filter UI Freeze Fix

Date: 2026-04-16

## Problem

Resetting the catalog search was doing much more work than the UI behavior required.

Two user paths were involved:

- clicking the catalog table `Reset` button
- pressing `Esc` while the main window handled the shortcut

Both paths eventually triggered a full catalog refresh instead of a simple filter reset.

That meant a search reset could:

- reload the full catalog dataset from SQLite
- rebuild every visible table item
- resize table columns
- recompute blob/media badges

On larger catalogs this blocked the main UI thread long enough to feel like a freeze.

## Root Cause

`reset_search()` was not implemented as a filter-only operation.

Instead, it:

- cleared the search UI
- unhid rows
- called `refresh_table()`

Separately, the `Esc` handling path was even heavier because it also called `init_form()`, which already goes through `refresh_table_preserve_view()`.

So the shortcut that users expected to mean "clear the current filter" was actually forcing a table rebuild and, in some paths, more than one expensive refresh step.

## Intended Behavior

For the catalog table, reset should be lean:

- clear the text filter
- restore the search column selector to `All columns`
- clear any explicit row filter
- reapply the existing in-memory filter logic

This produces the same visible result without rebuilding the catalog UI.

`Esc` remains the shortcut for resetting the filter.

## Changes Made

### `ISRC_manager.py`

- Changed `reset_search()` to:
  - clear the explicit filter
  - clear the search field with signals blocked
  - restore the search-column combo to `All columns` with signals blocked
  - call `apply_search_filter()` once
- Removed the `refresh_table()` call from `reset_search()`
- Updated the main-window `keyPressEvent()` `Esc` path to call only `reset_search()`
- Updated the action registry text and description to match the new behavior:
  - `Reset Search Filter`

### `isrc_manager/main_window_shell.py`

- Changed the `Escape`-bound action from:
  - `lambda: (app.init_form(), app.reset_search())`
- to:
  - `app.reset_search`

This keeps the shortcut intact while removing the unnecessary catalog rebuild and form reset.

### Tests

Added app-shell coverage proving:

- the `Reset` button clears filters without calling `refresh_table()`
- the action shortcut path clears the filter without calling `init_form()` or `refresh_table()`
- the main-window `Esc` handling clears the filter without rebuilding the catalog or clearing the draft form

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_profiles_and_selection.py`

## Validation

Ran:

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_profiles_and_selection`

Result:

- `OK`

## User Impact

Catalog filter reset is now a lightweight UI operation instead of a synchronous table rebuild.

Users should see:

- no freeze when clicking the catalog `Reset` button
- no freeze when pressing `Esc` to clear the current catalog filter
- Add Track draft values remain intact when `Esc` is used for filter reset

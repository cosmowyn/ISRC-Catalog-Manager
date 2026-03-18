# Workspace Layout Persistence Handoff

Current product version: `2.0.0`

Date: 2026-03-18

## Root-Cause Analysis

- `restoreState()` originally ran while only `addDataDock` and `catalogTableDock` existed, so the lazy catalog workspace docks were absent from the startup restore pass.
- `CatalogWorkspaceDock.show_panel()` re-tabified docks after they were shown, which could overwrite a saved layout with the default anchor arrangement.
- Base-dock `visibilityChanged` handlers fired during `closeEvent` teardown and wrote false values into `display/add_data_panel` and `display/catalog_table_panel`.
- `_apply_saved_view_preferences()` then reapplied those booleans after startup restore, which could clobber an otherwise valid restored dock layout.
- The app had no outer main-window geometry persistence at all.
- Test coverage verified live dock behavior but not close/reopen round trips.

## What Changed

- Startup now creates all persistent workspace `QDockWidget` shells before the first restore pass, while keeping the heavy inner panels lazy.
- Main-window restore is centralized in a one-time post-show path that restores geometry first, then dock state, then falls back to the legacy panel-visibility booleans only when no dock-state restore succeeds.
- Catalog workspace docks now carry lightweight placeholder widgets so they can participate in docking and restore before their real panels are materialized.
- Default tabification is now limited to docks that are still in their initial fallback-placement state. Restored docks are no longer re-tabified on show.
- Dock-state writes now go through a coalesced timer and are guarded during startup restore and shutdown.
- Base panel visibility prefs are now persisted from real live-session changes and from an explicit close-time snapshot, not from teardown noise.
- Outer main-window geometry and window state are now persisted under:
  - `display/main_window_geometry`
  - `display/main_window_window_state`

## Files Touched

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_workspace.py`
- `tests/test_app_shell_integration.py`

## Save / Restore Sequence

### Before

- Build shell.
- Restore dock state immediately.
- Apply saved view prefs, including base dock visibility.
- Create lazy workspace docks later on demand.
- Re-tabify docks on show.

### After

- Build shell.
- Create all persistent workspace dock shells immediately.
- Apply non-dock view prefs during init.
- On first show:
  - restore main-window geometry and outer window state if present
  - restore main-window dock state
  - apply base dock visibility prefs only when dock-state restore did not succeed
  - materialize visible lazy workspace panels
  - persist the resulting base panel visibility snapshot

## Regression Coverage

Added or updated coverage in `tests/test_app_shell_integration.py` for:

- workspace dock round-trip restore across close/reopen
- persistence of non-default dock placement
- hidden-catalog-table peer-tab restore
- startup restore winning over conflicting legacy visibility prefs
- close/reopen preservation of base panel visibility without teardown corruption
- outer main-window geometry round trip

Existing app-shell tests still cover:

- default first-open tabification
- hidden anchor behavior
- fullscreen and tab-bar behavior
- panel toggle actions

## Remaining Limitations

- This pass does not add any new floating-dock-specific restore policy beyond Qt's built-in `saveState()` behavior.
- The geometry round-trip persists the outer window state and size/position, but it intentionally does not change bootstrap behavior when no saved geometry exists.
- The workspace persistence logic still depends on Qt's `saveState(1)` contract, so future dock `objectName` changes would be a migration-sensitive change.

## Follow-Up Guidance

- Keep new persistent workspace docks on stable `objectName` values.
- If more dock families are added later, register their shell during startup so they can participate in restore.
- If a future pass changes floating-window policy, keep it separate from the non-floating workspace restore path implemented here.

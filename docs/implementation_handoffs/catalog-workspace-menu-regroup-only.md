# Catalog Workspace Menu Regroup Only

## Scope

This pass changed only the `Catalog > Workspace` submenu. No other Catalog submenus, top-level menus, ribbon structures, or workspace surfaces were reorganized.

## Previous Workspace submenu structure

- `Open and Manage`
  - `Catalog Managers…`
  - `Work Manager…`
  - `Release Browser…`
  - `Party Manager…`
  - `Contract Manager…`
  - `Contract Template Workspace…`
  - `Rights Matrix…`
  - `Deliverables & Asset Versions…`
  - `Derivative Ledger…`
  - `Global Search and Relationships…`
- `Panels`
  - `Show Add Track Panel`
  - `Show Catalog Table`

`Show Add Track Panel` and `Show Catalog Table` were real checkable toggle actions backed by the dock visibility persistence flow.

## New Workspace submenu structure

- `Create / Maintain`
  - `Add Track`
  - `Work Manager…`
  - `Party Manager…`
  - `Contract Manager…`
  - `Contract Template Workspace…`
  - `Rights Matrix…`
  - `Catalog Managers…`
- `Browse / Review`
  - `Catalog`
  - `Release Browser…`
  - `Deliverables & Asset Versions…`
  - `Derivative Ledger…`
  - `Global Search & Relationships…`

## Label changes made

- `Show Add Track Panel` is now presented in `Catalog > Workspace` as `Add Track`
- `Show Catalog Table` is now presented in `Catalog > Workspace` as `Catalog`
- `Global Search and Relationships…` is presented in `Catalog > Workspace` as `Global Search & Relationships…`

The underlying legacy toggle actions were left intact for dock-state synchronization and shortcut handling, but they are no longer exposed in the Workspace submenu.

## How checkbox/toggle behavior was removed for Catalog/Add Track

- Added Workspace-only proxy actions:
  - `workspace_add_track_action`
  - `workspace_catalog_action`
- These actions are plain non-checkable `QAction`s that call:
  - `open_add_track_workspace()`
  - `open_catalog_workspace()`
- Those methods open/show the existing dock, raise it, and focus the primary widget.
- The original checkable actions:
  - `add_data_action`
  - `catalog_table_action`
  remain in place for existing persistence and internal visibility sync, but they are no longer added to `Catalog > Workspace`.

## Files changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`

## Tests added or updated

- Updated app-shell menu structure assertions to verify:
  - `Catalog > Workspace` now contains `Create / Maintain` and `Browse / Review`
  - the new per-group order is correct
  - `Show Add Track Panel` and `Show Catalog Table` no longer appear in this submenu
  - `Add Track` and `Catalog` are non-checkable menu entries
- Added routing assertions showing the new Workspace-only `Add Track` and `Catalog` actions still open the correct dock and focus the primary widget
- Revalidated targeted workspace shell coverage:
  - `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_workspace_docks`
  - `python3 -m black --check ISRC_manager.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py`

## Risks and caveats

- The underlying toggle actions still exist because other shell code uses them for persisted dock visibility and state sync.
- Their labels remain unchanged internally; only the Workspace submenu presentation was changed.
- `Global Search & Relationships…` is currently a Workspace-menu-specific label proxy so the broader action text surface remains unchanged elsewhere.

## Explicit scope statement

This pass only changed the `Catalog > Workspace` submenu scope. No other Catalog submenus or top-level menu structures were modified.

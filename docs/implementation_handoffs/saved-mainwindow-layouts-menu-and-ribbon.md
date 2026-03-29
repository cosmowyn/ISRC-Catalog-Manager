# Saved Main Window Layouts Menu and Ribbon

## Current layout persistence seam used

- The feature layers on top of the existing main-window persistence seam in `App`.
- Geometry and outer window state continue to use:
  - `display/main_window_geometry`
  - `display/main_window_window_state`
  - `display/main_window_normal_geometry`
- Dock and tab arrangement continues to use Qt's existing `saveState(1)` / `restoreState(..., 1)` path through:
  - `display/main_window_dock_state`
- Base workspace-panel visibility still reuses the existing `display/add_data_panel` and `display/catalog_table_panel` settings.
- Named layouts do not introduce a second dock serializer or a second restore engine.

## Saved-layout backend added

- Added a named-layout store under:
  - `display/saved_main_window_layouts_json`
- Each saved layout captures the current:
  - main-window geometry
  - window-state marker
  - normal geometry
  - dock-state blob
  - Add Track panel visibility
  - Catalog Table panel visibility
  - Profiles ribbon visibility
  - Action ribbon visibility
- Applying a saved layout reuses the same geometry and dock restore helpers as startup restore, then refreshes visible lazy workspace docks and persists the result back through the existing anonymous startup layout keys.
- Duplicate layout names use overwrite confirmation instead of silently creating parallel near-duplicates.

## New `View -> Layout` structure

- `View`
  - `Columns`
  - `Show Profiles Ribbon`
  - `Show Action Ribbon`
  - `Customize Action Ribbon…`
  - `Layout`
    - `Saved Layouts`
    - `Add Layout`
    - `Delete Layout`
    - `Catalog Table`

## Table Layout relocation

- The old top-level `View -> Table Layout` submenu was removed.
- The existing table-layout controls were moved unchanged to:
  - `View -> Layout -> Catalog Table`
- Preserved controls:
  - `Edit Column Widths`
  - `Edit Row Heights`
  - `Allow Column Reordering`
- This pass does not merge table-header persistence into the named main-window layout store. The catalog-table header state remains on its existing per-profile seam.

## Menu saved-layout list behavior

- `Saved Layouts` is a dynamic submenu that rebuilds on open.
- When layouts exist, the submenu presents them in a scrollable `QListWidget` embedded in the menu via `QWidgetAction`.
- The list caps visible rows and scrolls when the saved-layout count exceeds that cap.
- When no layouts exist, the submenu shows a disabled `No Saved Layouts` placeholder.

## Ribbon dropdown behavior

- The Action Control Ribbon now includes a fixed saved-layout control cluster after the action spacer and before the customize button.
- The cluster contains:
  - a dropdown selector for saved layouts
  - a `Save Layout` button
  - a `Delete Layout` button
- The selector is disabled when no saved layouts exist and switches to the active saved layout after apply/save.
- This cluster is intentionally not part of the action-ribbon customizer model; it is a fixed workspace-control surface that still uses the same saved-layout backend as the menu.

## Add/delete interaction behavior

- `Add Layout`
  - prompts for a user-facing name
  - rejects blank names
  - prompts before overwrite when the name already exists
  - captures the current main-window arrangement only after the user confirms the name
- `Delete Layout`
  - offers the saved-layout list in a picker
  - confirms deletion before removing the entry
  - disables delete affordances again when the last saved layout is removed

## Tests added or updated

- Updated the View-menu structure regression to assert:
  - the new `Layout` subtree
  - `Saved Layouts`, `Add Layout`, `Delete Layout`
  - `Catalog Table` relocation
  - ribbon empty-state selector behavior
- Added a named-layout round-trip regression covering:
  - save with a name
  - persistence across close/reopen
  - apply from the ribbon dropdown
  - delete from the ribbon-backed workflow
  - shared data visibility in both the menu list and ribbon selector
- Added a scrollable-menu regression that proves the `Saved Layouts` submenu uses a bounded scrollable list widget when enough layouts exist.

## Risks and caveats

- Named layouts currently cover main-window arrangement and top-ribbon visibility state, but not customized action-ribbon contents.
- Catalog-table header order/visibility/width state remains a separate table-layout concern and is not bundled into the named main-window layout payload.
- The feature still depends on stable dock `objectName` values because it reuses Qt's existing dock-state blob.
- Applying a saved layout rebuilds the action ribbon because ribbon visibility remains part of the shared view-preference seam.

## Explicit shared-logic statement

The View menu and the Action Control Ribbon now share one saved-layout logic path. Save, list, apply, and delete all use the same named main-window layout backend; only the presentation differs between the scrollable menu list and the ribbon dropdown controls.

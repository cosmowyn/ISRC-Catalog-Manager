# Catalog Workspace UI Follow-Up Handoff

Date: 2026-03-18

## Status

This handoff reflects the current repository state after the UI follow-up changes landed.

Important scope note:

- this pass stayed UI-only
- no schema changes landed
- no payload or storage behavior changed
- no history or undo/redo semantics changed
- no dock-state version bump or destructive dock reset was introduced

The worktree is no longer clean in this snapshot because the changes described below are now present in code.

## What Was Implemented In This Pass

### 1. Catalog Managers now uses a scroll-safe, themed page wrapper

Implemented in:

- `isrc_manager/ui_common.py`
- `ISRC_manager.py`

What changed:

- `_create_scrollable_dialog_content()` was generalized so it can either:
  - build a normal `QScrollArea -> content -> layout` stack, or
  - install that scroll stack inside an existing outer page while preserving the outer widget identity
- the three `Catalog Managers` tab pages now use that helper directly:
  - `_CatalogArtistsPane`
  - `_CatalogAlbumsPane`
  - `_CatalogLicenseesPane`

Why this matters:

- the tab page object is still the real page shown by `panel.tabs.currentWidget()`
- bottom controls now stay reachable when the dock is tabbed, docked, or vertically constrained
- the scroll area, viewport, content widget, and outer page all receive the themed canvas role

### 2. Narrow canvas-role normalization landed for touched dock/tab pages

Implemented in:

- `isrc_manager/releases/dialogs.py`
- `isrc_manager/search/dialogs.py`

What changed:

- `ReleaseBrowserPanel.overview_tab` and `ReleaseBrowserPanel.tracks_tab` are now tagged with `role="workspaceCanvas"`
- `GlobalSearchPanel.right_container`, `results_tab`, and `relationships_tab` are now tagged with `role="workspaceCanvas"`
- stable attributes were added for those pages so tests can assert the role tagging directly without brittle widget-tree crawling

Why this stayed narrow:

- Release Browser already had `detail_scroll_area`
- Global Search already had `saved_searches_scroll_area`
- the real issue for those panels in this pass was untagged tab/page chrome, not missing scroll containers

### 3. "Show Add Data Panel" and "Show Catalog Table" were moved into Catalog

Implemented in:

- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`

What changed:

- the existing shared `QAction` objects were moved from the `View` menu into the `Catalog` menu
- the same action instances are still used everywhere
- their action-ribbon registry category was changed from `View` to `Catalog`

What was preserved:

- shortcuts
- checked state
- signal wiring
- dock visibility sync
- Enter-to-save gating that depends on `add_data_action`
- settings persistence and history bundle behavior attached to the existing actions

### 4. Hidden Catalog Table no longer blocks workspace dock opening

Implemented in:

- `isrc_manager/catalog_workspace.py`

What changed:

- `_default_tab_anchor()` now skips hidden, floating, or otherwise non-usable anchor docks
- if `catalog_table_dock` is hidden, later workspace docks use visible peers instead of tabifying against the hidden dock

Behavioral result:

- hiding Catalog Table no longer strands new catalog workspace docks
- the first newly opened dock remains visible
- later docks still tabify against visible workspace peers

### 5. The 5px top-chrome / dock-tab separation landed without adding a new persisted surface

Implemented in:

- `isrc_manager/main_window_shell.py`
- `isrc_manager/theme_builder.py`
- `ISRC_manager.py`

What changed:

- the existing bottom top-toolbar row, `profilesToolbar`, now carries the 5px boundary
- `profilesToolbar` gets a fixed bottom contents margin of 5px
- the stylesheet paints a 5px bottom border on `QToolBar#profilesToolbar` using `toolbar_border`
- refresh hooks re-apply the boundary after:
  - resize
  - show
  - fullscreen/showNormal window-state changes
  - action-ribbon visibility toggles

Important implementation detail:

- this is not a new widget
- this is not a new toolbar row
- this does not affect `saveState(1)` persistence contracts
- the boundary is a layout-backed band on the existing toolbar plus QSS styling on that same toolbar

### 6. The action ribbon is now a separate theme-builder surface

Implemented in:

- `isrc_manager/theme_builder.py`
- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`
- `isrc_manager/qss_reference.py`
- `docs/theme_builder.md`

What changed:

- additive theme keys were added:
  - `action_ribbon_bg`
  - `action_ribbon_fg`
  - `action_ribbon_border`
- all three fall back to the existing `toolbar_*` tokens when unset
- the real action ribbon toolbar now exposes:
  - object name `#actionRibbonToolbar` (preserved)
  - `role="actionRibbonToolbar"` (new additive hook)
- the theme builder now includes a top-level `Action Ribbon` tab
- the live preview now includes a dedicated `Action Ribbon` preview page that uses the real ribbon selectors
- the selector reference now explicitly exposes:
  - `QToolBar#actionRibbonToolbar`
  - `QToolBar[role="actionRibbonToolbar"]`
  - `QToolButton[role="actionRibbonButton"]`

### 7. Bundled themes now deliberately style the action ribbon

Implemented in:

- `isrc_manager/starter_themes.py`

Updated bundled themes:

- Apple Light
- Apple Dark
- High Visibility
- Aeon Emerald Gold
- Subconscious Cosmos
- VS Code Dark
- Pastel Studio

What changed:

- each bundled theme now sets explicit `action_ribbon_*` values
- the values are intentionally distinct from tab chrome
- High Visibility keeps a strong high-contrast ribbon treatment

## What Was Intentionally Deferred

The following items were intentionally left for a later pass:

- ribbon-button-specific theme tokens
- ribbon-button-specific focus and checked-state tokenization
- a broader repo-wide audit of every untagged tab/page wrapper
- wrapping any additional windows beyond `Catalog Managers`
- changes to Add Data tab-page role tagging
- changes to Work Manager or other unrelated workspace layouts beyond the hidden-anchor fix
- dock-state versioning, dock-state resets, or any persisted toolbar/dock-layout contract changes
- any broader chrome redesign beyond the 5px boundary requirement

## Confirmed Root Causes

### 1. Catalog Managers was the only confirmed Catalog-menu overflow target in this pass

Confirmed in `ISRC_manager.py`:

- the three manager panes were plain widgets
- they contained a 420px-minimum table
- bottom action rows could drop below the visible viewport when the dock was tabbed/docked/small

### 2. Release Browser and Global Search were not missing the same scroll structure

Confirmed in:

- `isrc_manager/releases/dialogs.py`
- `isrc_manager/search/dialogs.py`

Reasoning:

- Release Browser already had `detail_scroll_area`
- Global Search already had `saved_searches_scroll_area`
- the follow-up problem there was themed canvas propagation on untagged page wrappers, not bottom controls sitting outside an unwrapped page

### 3. The menu actions already had the correct behavioral wiring

Confirmed in:

- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`

Reasoning:

- `add_data_action` and `catalog_table_action` already existed as the correct shared `QAction` instances
- recreating them would have risked shortcuts, checked-state sync, settings persistence, and history-bundle behavior

### 4. The top-chrome issue was a zero-gap layout boundary, not a tab-color bug

Confirmed in:

- `isrc_manager/main_window_shell.py`
- runtime geometry inspection during implementation

Root cause:

- the bottom visible toolbar row sat flush against the dock-tab region
- a new separator toolbar would have risked toolbar persistence and state saving
- the safe fix was to enlarge the existing bottom toolbar row and style its boundary directly

### 5. The ribbon already had stable hooks, but only shared toolbar tokens

Confirmed in:

- `isrc_manager/main_window_shell.py`
- `ISRC_manager.py`
- `isrc_manager/theme_builder.py`

Root cause:

- `#actionRibbonToolbar` already existed
- `actionRibbonButton` was already exposed on the real ribbon buttons
- there was no dedicated theme-builder page or dedicated ribbon-bar color token set

## Specific Risks Encountered During Implementation

- `QToolBar` border styling alone did not create the required separation; the fix needed both layout space and QSS painting.
- Adding a new toolbar row would have been risky because the app persists top toolbar/dock layout state with `saveState(1)`.
- The scroll helper needed to preserve tab-page identity, otherwise existing assumptions like `panel.tabs.currentWidget() is panel.artists_tab` would have broken.
- Full offscreen Qt integration runs are noisy and slow; targeted attributes were added on touched release/search pages so the new themed-surface coverage could be tested directly without brittle tree walking.

## Partial Fixes Or Compromises

- The action ribbon is separately themable only at the bar/chrome level in this pass.
- Ribbon buttons still use the shared `button_*` styling surface.
- Only the confirmed Catalog Managers overflow case received the new wrapper.
- Canvas-role normalization was intentionally limited to the touched Release Browser and Global Search page wrappers instead of becoming a repo-wide cleanup.

## Why Only Certain Windows And Pages Were Touched

`Catalog Managers` was the only confirmed Catalog-menu window that still made bottom controls unreachable when docked/tabbed/small.

`Release Browser` and `Global Search` were not wrapped further because:

- they already had the relevant scroll areas for the overflow-prone content
- the narrower risk in this pass was the untagged themed-surface fallback on specific page wrappers

This pass therefore touched:

- `Catalog Managers` for scroll wrapping and themed propagation
- `Release Browser` for tab-page role normalization
- `Global Search` for container/tab-page role normalization

## Remaining Untagged Or Unwrapped Surfaces Discovered

These were noted during inspection but intentionally left unchanged:

- Add Data top-level tab pages in `isrc_manager/main_window_shell.py`
- additional work-related and other workspace tab/page wrappers outside the touched Catalog follow-up scope
- legacy modal/dialog surfaces not involved in the Catalog workflow requested here

These should be treated as follow-up candidates, not accidental omissions.

## Theme And Styling Limitations Still Remaining

- `action_ribbon_*` only styles the ribbon bar itself
- ribbon buttons still inherit shared button tokens
- button-to-ribbon chrome mismatch can still exist in themes that choose very different ribbon and button colors
- stronger ribbon-specific focus styling remains a future enhancement

## Files Changed In This Pass

- `ISRC_manager.py`
- `docs/theme_builder.md`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/qss_reference.py`
- `isrc_manager/releases/dialogs.py`
- `isrc_manager/search/dialogs.py`
- `isrc_manager/starter_themes.py`
- `isrc_manager/theme_builder.py`
- `isrc_manager/ui_common.py`
- `tests/test_app_shell_integration.py`
- `tests/test_qss_reference.py`
- `tests/test_theme_builder.py`
- `tests/test_ui_common.py`

## Tests Added Or Updated

- `tests/test_ui_common.py`
  - generalized scroll helper behavior
  - preserved outer-page identity
  - themed role propagation to page/scroll area/viewport/content
- `tests/test_app_shell_integration.py`
  - Catalog Managers themed scroll reachability
  - Catalog menu relocation
  - preserved toggle behavior and settings persistence
  - hidden Catalog Table anchor behavior
  - touched dock/tab page role coverage
  - 5px top-chrome boundary persistence across ribbon/window-state changes
- `tests/test_theme_builder.py`
  - new `action_ribbon_*` defaults and fallback behavior
  - Action Ribbon builder tab and live preview routing
  - bundled-theme ribbon coverage
  - High Visibility ribbon readability coverage
- `tests/test_qss_reference.py`
  - new action-ribbon selector exposure

Verified test runs during this pass:

- `QT_QPA_PLATFORM=offscreen python3 -m unittest -v tests.test_ui_common tests.test_theme_builder tests.test_qss_reference`
- `QT_QPA_PLATFORM=offscreen python3 -m unittest -v tests.test_repertoire_dialogs tests.test_qss_autocomplete tests.test_history_manager`
- `QT_QPA_PLATFORM=offscreen python3 -m unittest -v tests.test_app_shell_integration`

Observed result:

- all targeted suites passed
- `tests.test_app_shell_integration` passed in full after the menu-relocation test fix

## Recommended Next Implementation Order

1. Audit and normalize the remaining untagged workspace page wrappers, starting with Add Data and the next-most-visible docked/tabbed surfaces.
2. Decide whether the action ribbon needs button-level tokenization or whether Advanced QSS is sufficient for the project.
3. If ribbon button tokenization is approved, add a dedicated builder surface and preview coverage for button chrome and focus states.
4. Only after the above, consider any broader workspace layout cleanup for dialogs and legacy panels that were intentionally left out of this pass.

## Recommended Tests For The Next Pass

- add render-oriented checks for remaining untagged dock/tab pages once more of them are normalized
- add direct tests for Add Data tab-page roles if those pages are normalized later
- add ribbon-button preview and export/import coverage if button tokenization is introduced
- add more anchor-behavior tests for combinations involving floating workspace docks and visible Add Data docks
- add any new scroll-reachability tests only for windows that are actually wrapped, not speculative future wrappers


# Post-Storage UI Follow-Ups: Governance And Work Manager

## Summary

This handoff documents the UI/controller fixes that landed after the local storage/history handoff in [`hard-cap-snapshot-retention-and-storage-admin-routing.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/hard-cap-snapshot-retention-and-storage-admin-routing.md).

These follow-ups are narrower than that storage/history pass. They do not change retention, cleanup, or storage-budget behavior. They address three separate regressions that were discovered afterward:

1. catalog refreshes were polluting undo history with repeated `Adjust Column Widths`
2. the docked `Add Track` surface could be shown in an uninitialized state, leaving Work Governance combos blank/inert
3. `Work Manager` could vertically compress its action stack so the selection banner overlapped the bottom row of buttons

## Previous Local Handoff Gap

The local repo already contains the storage/history handoff, but that document does not describe these later UI fixes:

- catalog header resize history gating
- Add Track dock self-initialization when opened through workspace/dock visibility paths
- Work Manager control-stack layout stabilization under larger fonts / tighter dock geometry

This file is the addendum for those changes.

## Files Touched

### Runtime

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/main_window_shell.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/main_window_shell.py)
- [`isrc_manager/ui_common.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/ui_common.py)
- [`isrc_manager/selection_scope.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/selection_scope.py)
- [`isrc_manager/works/dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/works/dialogs.py)

### Tests

- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [`tests/app/test_app_shell_profiles_and_selection.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_profiles_and_selection.py)
- [`tests/app/test_app_shell_editor_surfaces.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_editor_surfaces.py)
- [`tests/app/test_app_shell_workspace_docks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

## 1. Header Resize History Cleanup

### Problem

Catalog refresh/layout work was emitting visible undo entries labeled `Adjust Column Widths` even when the resize came from programmatic table work rather than an explicit user drag.

This cluttered undo history with non-meaningful entries and made real user actions harder to find.

### Implementation

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py:12067):

- added `_should_record_header_resize_history()`
- gated `_on_header_sections_resized(...)` behind:
  - layout/history suspension still being off
  - interactive column-width mode being enabled
  - an actual mouse-button-driven resize being in progress

The behavior now separates:

- programmatic refresh/layout resizes: persist width state if needed, but do not create visible history entries
- true user drag resizes in interactive width mode: record one visible history action

### Result

Undo history no longer fills with refresh-induced `Adjust Column Widths` entries.

## 2. Add Track Governance Self-Initialization

### Problem

The docked `Add Track` panel could be opened through workspace visibility/layout restore paths without going through `open_add_track_entry()`.

That left the panel in an uninitialized state:

- Work Governance combos could be empty
- lookup combos could still be blank
- the context-return button could appear when it should not
- the surface looked broken even though the underlying services were present

This was especially visible when the dock was reopened from workspace actions rather than from the explicit `Add Track…` flow.

### Implementation

In [`isrc_manager/main_window_shell.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/main_window_shell.py:925):

- the governance combos now start with safe placeholder/default items at construction time
- the `Open Work Manager` return button starts hidden
- the Add Track dock `visibilityChanged` signal now routes through a dedicated app handler

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py:15809):

- added `_refresh_add_track_lookup_sources_preserving_text()`
  - refreshes Add Track lookup combos without wiping current typed values
- added `_ensure_add_track_panel_initialized()`
  - rebuilds governance state
  - repopulates lookup combos if the dock is visible but still empty
- added `_on_add_track_dock_visibility_changed(...)`
  - keeps dock visibility syncing behavior
  - triggers the safe initialization path when the dock becomes visible

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py:13226) and [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py:18374):

- `_apply_add_data_panel_state(True)` now ensures the panel is initialized once the dock is shown
- `open_add_track_workspace()` now uses the same initialization path

### Important behavior constraint

This was implemented to avoid destroying in-progress drafts.

The initializer:

- rebuilds missing combo state
- refreshes governance UI
- preserves current draft text and selected context when the panel already has real user data

It is not a silent `clear_form_fields()` path.

### Result

The Add Track dock now opens correctly even when shown through workspace/dock restore flows, and it still preserves real draft state when reopening an already-active entry.

## 3. Work Manager Control Stack Layout Fix

### Problem

`Work Manager` has a tall top control section:

- search row
- two-column action-button cluster
- selection-scope banner

Under larger fonts or constrained dock geometry, the stack could vertically compress incorrectly. The visible symptom was:

- the `Catalog selection` banner and text riding on top of the bottom action buttons
- button rows becoming visually or functionally inaccessible

### Root cause

The shared action cluster and the selection-scope banner were both relying too much on optimistic/initial size assumptions. When effective font metrics changed after polish/layout, the containers did not consistently re-reserve their full height.

### Implementation

In [`isrc_manager/ui_common.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/ui_common.py:400):

- `_create_action_button_cluster(...)` now:
  - uses a less compressible vertical size policy
  - activates its grid layout before final sizing
  - reserves at least the maximum of:
    - the manual lower-bound row calculation
    - `minimumSizeHint().height()`
    - `sizeHint().height()`

In [`isrc_manager/selection_scope.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/selection_scope.py:80):

- `SelectionScopeBanner` now:
  - uses a non-compressing vertical size policy
  - recalculates its minimum height after state/text updates
  - listens for font/style/layout changes and re-syncs its height

In [`isrc_manager/works/dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/works/dialogs.py:939):

- `WorkBrowserPanel` now schedules a control-height sync after:
  - initial construction
  - selection-scope refreshes
  - font/layout/resize/show/style events
- that sync re-polishes and reactivates:
  - the action cluster
  - the selection banner
  - the containing `Find and Manage` section

### Result

The `Work Manager` top section now maintains stable vertical separation between:

- the action button cluster
- the `Catalog selection` banner

even when fonts expand or the dock goes through layout recalculation.

## Tests Added

### Header-resize history

In [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py:2977):

- `case_programmatic_header_resize_does_not_record_history`
- `case_interactive_header_resize_records_a_single_visible_history_entry`

Wired through [`tests/app/test_app_shell_profiles_and_selection.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_profiles_and_selection.py:33).

### Add Track dock initialization

In [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py:5954):

- `case_add_track_workspace_initializes_governance_controls_when_shown_without_entry_reset`
- `case_add_track_workspace_show_preserves_existing_draft_and_work_context`

Wired through [`tests/app/test_app_shell_editor_surfaces.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_editor_surfaces.py:9).

### Work Manager layout stability

In [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py:3302):

- `case_work_manager_controls_remain_non_overlapping_when_fonts_expand`

This test intentionally inflates the Work Manager font sizes and asserts:

- the selection banner starts below the action cluster
- action-cluster child buttons remain inside the cluster bounds
- selection-banner children remain inside the banner bounds

Wired through [`tests/app/test_app_shell_workspace_docks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py:23).

## Validation Performed

### For header-resize history

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_profiles_and_selection tests.test_history_budget_hooks tests.test_ui_common`

### For Add Track governance initialization

- `python3 -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces`

### For Work Manager layout stability

- `python3 -m py_compile isrc_manager/ui_common.py isrc_manager/selection_scope.py isrc_manager/works/dialogs.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_workspace_docks.AppShellWorkspaceDockTests.test_work_manager_controls_remain_non_overlapping_when_fonts_expand`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_workspace_docks`

## Known Limits / Follow-Up Notes

- The Work Manager height stabilization is currently panel-specific at the top-level sync layer. The lower-level shared helpers are improved, but only `WorkBrowserPanel` currently adds the extra event-driven height reconciliation for its stacked controls.
- The Add Track self-initialization path intentionally avoids a full form reset. If future work adds more lazily populated widgets to that dock, they should be folded into `_refresh_add_track_lookup_sources_preserving_text()` or another preservation-safe initializer instead of reviving a blanket reset-on-show behavior.
- The header resize history gate is intentionally conservative. If keyboard-driven column-width editing is later added as a first-class feature, the recording predicate will need to be broadened beyond the current mouse-driven check.

## Relationship To Prior Intended Logic

These changes do not alter the storage/history contract from the prior local handoff. They are follow-up UI integrity fixes:

- make undo history reflect meaningful user actions
- make Add Track governance controls truthful when the dock is shown by layout/workspace flows
- keep Work Manager controls accessible under real theme/font/layout pressure

They refine the usability of the existing architecture without changing its core workflow intent.

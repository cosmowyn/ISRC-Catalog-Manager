# V3 Workflow Revision Phase 3

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 3 is `in_progress`.

This first Phase 3 slice rewires real shell behavior so `Work Manager` can launch governed child-track creation through the existing `Add Track` dock instead of keeping track creation entirely floating and track-first.

## Phase Goal

Make `Work Manager` the primary creation and governance surface for parent works and child tracks.

## What Changed

- `Work Manager` now exposes an explicit `Add Track to Work` action in the reusable panel and dialog wrapper.
- The main window now supports a visible work-governance creation context inside the existing `Add Track` dock:
  - active work summary
  - child relationship selector
  - optional parent-track selector
  - clear-context action
- Creating a track from that context now passes `work_id`, `parent_track_id`, and `relationship_type` into `TrackCreatePayload` before save.
- Creating a new work now offers immediate first-track creation when the work was created without linked tracks.
- The existing `Add Track` dock remains the recording editor for this slice, but it is no longer purely blind to work governance when launched from `Work Manager`.

## Source Of Truth Files And Surfaces

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`

## Tests Added Or Updated

- Added controller coverage for the new `Work Manager` child-track action and its empty-selection behavior.
- Added shell coverage for:
  - launching governed child-track creation from `Work Manager`
  - saving a child track with `work_id` / lineage fields populated
  - prompting for first-track creation immediately after a new work is created
- Updated workspace-dock layout coverage to reflect the new `Add Track to Work` control in the `Work Manager` action cluster.
- Validation run:
  - `python3 -m unittest tests.test_dialog_controller_behaviors tests.test_repertoire_dialogs`
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_workspace_docks`

## What Was Intentionally Deferred

- de-emphasizing the global floating `Add Track` menu/ribbon/help copy
- `Add Album...` bulk creation rewrite so it also respects work-governed creation
- Catalog operational cleanup and work-linked issue routing from quality/search
- final legacy license deletion and shell cleanup

## Risks And Caveats

- The work-context path is now real, but the app still advertises floating `Add Track` creation in menus, ribbon defaults, and help copy. That still needs to be demoted in a later Phase 3 slice.
- `Add Album...` still bypasses work-governed creation and remains a parallel track-first route.
- Work seeding currently pre-fills the track title and ISWC on context launch only. Later track edits still remain independent and do not overwrite work metadata.

## Workers Used And Workers Closed

- Workers used:
  - `Pasteur`
  - `Ptolemy`
  - `Dirac`
- Workers closed:
  - `Pasteur`
  - `Ptolemy`
  - `Dirac`

## QA/QC Summary From Central Oversight

The first Phase 3 landing is coherent with the v3 product direction:

- `Work Manager` now has a genuine child-track creation route instead of only post-hoc linking.
- The existing `Add Track` dock is being repurposed as a recording editor that can operate under explicit work governance.
- The shell now supports “create work, then create first track immediately” without inventing a second recording editor.

The phase is not ready to close yet because floating track-first affordances still remain prominent elsewhere in the product shell.

## Exact Safe Pickup Instructions

Next safe Phase 3 continuation:

1. read this handoff and the Phase 2 handoff first
2. continue from the new work-context helpers in `ISRC_manager.py` rather than inventing a second track editor
3. demote floating `Add Track` copy and affordances so `Work Manager` becomes the clear conceptual entry point
4. rewrite `Add Album...` so bulk/album creation does not remain an unmanaged track-first bypass
5. then move into Catalog/quality/search routing work without turning Catalog into a second governance entry point

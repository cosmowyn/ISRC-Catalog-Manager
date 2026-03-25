# V3 Workflow Revision Phase 3

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 3 is `in_progress`.

This Phase 3 checkpoint now covers two connected runtime slices:

- `Work Manager` can launch governed child-track creation through the existing `Track Entry` dock instead of keeping track creation entirely floating and track-first.
- `Work Manager` can also launch governed album batches, and the album dialog now writes work-governed child tracks instead of leaving album creation as an unmanaged bypass.

## Phase Goal

Make `Work Manager` the primary creation and governance surface for parent works and child tracks.

## What Changed

- `Work Manager` now exposes an explicit `Add Track to Work` action in the reusable panel and dialog wrapper.
- `Work Manager` now exposes an explicit `Add Album to Work` action in the reusable panel and dialog wrapper.
- The main window now supports a visible work-governance creation context inside the existing `Add Track` dock:
  - active work summary
  - child relationship selector
  - optional parent-track selector
  - clear-context action
- Creating a track from that context now passes `work_id`, `parent_track_id`, and `relationship_type` into `TrackCreatePayload` before save.
- Creating a new work now offers immediate first-track creation when the work was created without linked tracks.
- The existing `Add Track` dock has been repositioned as `Track Entry` across the shell, ribbon, and help copy so it reads as a recording-entry/admin surface rather than the conceptual start of the product.
- The album dialog now supports a `Work Governance` section with:
  - shared parent-work selection
  - batch relationship-type selection
  - seeded locked context when opened from `Work Manager`
- Saving an album batch now behaves in one of two governed ways:
  - if a parent work is selected, every created track inherits that `work_id` plus the chosen relationship type
  - if no parent work is selected, the dialog creates one new parent work per saved track so the batch still lands in the governed v3 model
- The shell now promotes `Work Manager` in the workspace menu and action-ribbon defaults, while the track-entry toggle is explicitly labeled `Show Track Entry Panel`.

## Source Of Truth Files And Surfaces

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`

## Tests Added Or Updated

- Added controller coverage for the new `Work Manager` child-track action and its empty-selection behavior.
- Added controller coverage for the new `Work Manager` album-batch action and its empty-selection behavior.
- Added shell coverage for:
  - launching governed child-track creation from `Work Manager`
  - saving a child track with `work_id` / lineage fields populated
  - prompting for first-track creation immediately after a new work is created
- Added shell coverage for:
  - launching `Add Album to Work` from a selected work
  - saving an album batch under a selected work with a chosen child relationship type
  - saving an album batch without a selected work and automatically creating one parent work per track
- Updated workspace-dock layout coverage to reflect the new `Add Album to Work` control in the `Work Manager` action cluster.
- Updated startup and menu coverage to reflect the `Track Entry` rename and the promoted `Work Manager` ribbon default.
- Validation run:
  - `python3 -m unittest tests.test_dialog_controller_behaviors tests.test_repertoire_dialogs`
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_workspace_docks`
  - `python3 -m unittest tests.app.test_app_shell_startup_core`

## What Was Intentionally Deferred

- Catalog operational cleanup and work-linked issue routing from quality/search
- final legacy license deletion and shell cleanup
- any deeper modeling for multi-work albums where one release batch intentionally spans multiple unrelated works
- any additional shell pruning beyond the current `Track Entry` demotion and `Work Manager` promotion

## Risks And Caveats

- Work seeding currently pre-fills the track title and ISWC on context launch only. Later track edits still remain independent and do not overwrite work metadata.
- When album batches are saved without a shared parent work, the auto-created works currently seed from the track title and ISWC only. Richer work metadata capture for that path remains a later enhancement.
- A governed album batch under one selected work assumes the batch belongs to one composition-level parent. More advanced multi-work batch authoring is intentionally not modeled in this slice.
- The `Track Entry` panel still exists as a direct recording/admin surface for imports, repairs, and exceptional cases; it has been demoted conceptually, not removed.

## Workers Used And Workers Closed

- Workers used:
  - `Pasteur`
  - `Ptolemy`
  - `Dirac`
  - `Goodall`
  - `Boyle`
- Workers closed:
  - `Pasteur`
  - `Ptolemy`
  - `Dirac`
  - `Goodall`
  - `Boyle`

## QA/QC Summary From Central Oversight

The first Phase 3 landing is coherent with the v3 product direction:

- `Work Manager` now has a genuine child-track creation route instead of only post-hoc linking.
- The existing `Add Track` dock is being repurposed as a recording editor that can operate under explicit work governance.
- The shell now supports “create work, then create first track immediately” without inventing a second recording editor.
- Album-batch creation no longer remains outside the governed model; it now either links under a selected work or creates parent works automatically so new album tracks are not orphaned from work governance.
- Work Manager is becoming the clear conceptual entry point while `Track Entry` remains available for operational exceptions and direct recording maintenance.

The phase is not ready to close yet because quality/search issue routing and the remaining work-governance follow-through still need to be aligned before Catalog-facing cleanup begins.

## Exact Safe Pickup Instructions

Next safe Phase 3 continuation:

1. read this handoff and the Phase 2 handoff first
2. continue from the new work-context helpers in `ISRC_manager.py` rather than inventing a second track editor
3. continue from the governed album path rather than creating a second batch-entry surface
4. route quality/search/work-linkage follow-up back into `Work Manager` so governance issues resolve at the parent layer
5. only after that, move into Catalog/quality/search cleanup without turning Catalog into a second governance entry point

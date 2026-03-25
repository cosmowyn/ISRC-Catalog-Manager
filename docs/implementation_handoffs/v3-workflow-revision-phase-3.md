# V3 Workflow Revision Phase 3

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 3 is `completed`.

This completed Phase 3 handoff covers three connected runtime slices:

- `Work Manager` can launch governed child-track creation through the existing `Track Entry` dock instead of keeping track creation entirely floating and track-first.
- `Work Manager` can also launch governed album batches, and the album dialog now writes work-governed child tracks instead of leaving album creation as an unmanaged bypass.
- quality/search governance follow-up now routes back into `Work Manager` instead of dropping the user into unrelated record editors when the real task is work assignment or work-level governance.

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
- `Work Manager` can now be opened with:
  - a focused work row for work-level navigation from search/results surfaces
  - a pinned track-scope override for governance triage when a track needs to be assigned to a work
- Relationship search now opens a specific work result inside `Work Manager` instead of opening the manager generically with no focused target.
- Quality dashboard triage now routes governance issues back into `Work Manager`:
  - work-entity issues open the focused work row
  - `track_missing_linked_work` opens `Work Manager` with the affected track pinned as the scope to resolve

## Source Of Truth Files And Surfaces

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/quality/dialogs.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`
- `tests/test_quality_dialogs.py`

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/quality/dialogs.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`
- `tests/test_quality_dialogs.py`

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
- Added shell coverage for:
  - opening a specific work result from relationship search and focusing the requested work inside `Work Manager`
  - routing `track_missing_linked_work` triage into `Work Manager` with a pinned track scope override
- Updated quality-dialog coverage so entity filtering is driven by real scan result entities and the open action is phrased generically enough for manager/workspace routing.
- Updated workspace-dock layout coverage to reflect the new `Add Album to Work` control in the `Work Manager` action cluster.
- Updated startup and menu coverage to reflect the `Track Entry` rename and the promoted `Work Manager` ribbon default.
- Validation run:
  - `python3 -m unittest tests.test_dialog_controller_behaviors tests.test_repertoire_dialogs`
  - `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_workspace_docks`
  - `python3 -m unittest tests.app.test_app_shell_startup_core`
  - `python3 -m unittest tests.test_quality_dialogs`

## What Was Intentionally Deferred

- Catalog operational cleanup beyond the routing closeout
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

Phase 3 is coherent and ready to close against the v3 product direction:

- `Work Manager` now has a genuine child-track creation route instead of only post-hoc linking.
- The existing `Add Track` dock is being repurposed as a recording editor that can operate under explicit work governance.
- The shell now supports “create work, then create first track immediately” without inventing a second recording editor.
- Album-batch creation no longer remains outside the governed model; it now either links under a selected work or creates parent works automatically so new album tracks are not orphaned from work governance.
- Work Manager is becoming the clear conceptual entry point while `Track Entry` remains available for operational exceptions and direct recording maintenance.
- Governance triage no longer dead-ends in the wrong places: search and quality now send work-related follow-up back into `Work Manager`, which is the right parent-governance surface for assignment and repair.

Central Oversight sign-off:

- Phase 3 can close because the main creation path, batch path, and governance triage path now all converge on `Work Manager` as the parent surface.
- The next work should move into Phase 4 read-side cleanup rather than adding more shell reshaping to Phase 3.

## Exact Safe Pickup Instructions

Next safe continuation:

1. read this handoff and the Phase 2 handoff first
2. treat Phase 3 as closed unless a concrete bug is found in the governed creation or governance-routing paths
3. begin Phase 4 from the read-side authority cleanup in catalog and quality surfaces
4. keep Catalog as the operational inventory, not a second governance entry point
5. keep final legacy-license deletion out of Phase 4 unless the authoritative replacements are already fully landed

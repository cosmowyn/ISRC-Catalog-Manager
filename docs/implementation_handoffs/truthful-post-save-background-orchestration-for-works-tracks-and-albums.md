# Truthful Post-Save Background Orchestration for Works, Tracks, and Albums

## Summary

This patch fixes the post-save UI hang that occurred after add/delete flows for works, tracks, and albums by moving the safe heavy work off the UI thread and by finishing progress only after the main-thread UI is actually ready again.

The implementation reuses the existing background task stack instead of inventing a new loader path:

- `BackgroundTaskManager`
- `App._submit_background_bundle_task(...)`
- `on_success_before_cleanup`
- `TaskUiProgressContext`

It also extends the same truthful-completion model to the remaining track editor save flows so single-track and bulk track saves no longer perform their heavy final refresh work in the old post-dialog-close phase.

## Why This Changed

The real hang source was not the database write itself. The blocking work happened after the mutation:

- full catalog dataset reloads
- combobox/lookup refreshes
- header/view restoration
- table rebuild/population
- blob badge recomputation
- work manager / governance refreshes
- selection and focus restoration

Several add/delete/save paths were doing that work synchronously on the main thread after the write finished, or they were using `on_success` instead of `on_success_before_cleanup`, which allowed the loader to complete before the UI was actually usable again.

That produced two bad outcomes:

- the UI appeared hung after save/delete
- the progress dialog could imply completion before the UI refresh had really finished

## Files / Layers Affected

### Runtime orchestration

- `ISRC_manager.py`
  - `save()` at `17031`
  - `_delete_unused_albums_in_background()` at `20727`
  - `create_work()` at `20816`
  - `update_work()` at `21016`
  - `delete_work()` at `21214`
  - `delete_entry()` at `24431`
  - `AlbumEntryDialog.save_album()` at `29938`
  - `EditDialog._save_single_changes()` at `31271`
  - `EditDialog._save_bulk_changes()` at `31634`
- `isrc_manager/services/import_governance.py`
  - `GovernedImportCoordinator.create_governed_tracks_batch()` at `298`

### Tests

- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/app/test_app_shell_profiles_and_selection.py`

## Original Hang Source

The write-side mutations were already background-safe once they ran through bundle services, but the catalog/UI hydration work after those mutations was still large enough to block interaction:

1. write transaction finishes
2. history snapshot/action is recorded
3. catalog rows and lookup values are reloaded
4. table headers / rows / badges / view state are rebuilt
5. work manager and governance controls are refreshed
6. selection/focus is restored

Before this patch, multiple flows performed step 4-6 in the wrong lifecycle phase or directly on the main thread without truthful loader ownership semantics.

## What Moved Off-Thread

Safe worker-thread work now includes:

- governed track creation
- governed album batch creation
- work create / update / delete mutations
- track delete mutation
- unused album cleanup mutation
- track edit / bulk edit mutations
- history snapshot recording
- release synchronization
- refreshed catalog dataset loading from the background bundle
- refreshed catalog combo/lookup value loading from the background bundle

These worker steps report real milestones through `ctx.report_progress(...)`.

## What Stays On The Main Thread

UI-only work remains on the main thread:

- applying the refreshed catalog dataset to widgets
- rebuilding table headers/items
- restoring header state, sort, scroll position, and selection
- refreshing visible workspace panels
- updating add-track governance controls
- closing dialogs / surfacing final success state

This work now runs in `on_success_before_cleanup(...)`, not after the loader is already considered done.

## Progress / Loading Semantics

The loader now stays truthful across these flows:

- worker progress reports real mutation/history/load milestones only
- worker completion is capped below 100%
- UI refresh progress is reported from `on_success_before_cleanup(...)`
- `100%` is emitted only after:
  - background mutation is done
  - the UI connection is committed
  - the refreshed dataset/lookup values are applied
  - history/actions are refreshed
  - selection/view restoration is complete
  - dependent workspace/governance panels are updated

The dialog closes only after that phase completes.

### Concrete rule now used

- worker-side progress stops at the final truthful worker milestone, usually `89%`
- UI-side progress covers the remaining application work
- `100%` is emitted only when the UI is actually ready

## Operation Coverage

### Tracks

- Add/governed save now:
  - creates the track/work in the worker
  - records history in the worker
  - synchronizes releases in the worker
  - loads the refreshed catalog dataset in the worker
  - applies the dataset and governance refresh on the main thread before completion

- Delete now:
  - deletes in the worker
  - reloads refreshed catalog data in the worker
  - restores UI selection/history/governance state before emitting `100%`

- Edit/save now:
  - no longer leaves propagated album-metadata saves on the synchronous path
  - single-track and bulk-track saves now use the same truthful completion model
  - final catalog refresh no longer lives in `on_success`

### Works

- Create/update/delete now:
  - use background bundle tasks
  - load refreshed catalog data when linked tracks require it
  - refresh the work manager and governance state before loader completion

### Albums

- Album batch save now:
  - creates tracks in the worker
  - reports real per-track batch progress from `GovernedImportCoordinator.create_governed_tracks_batch(...)`
  - synchronizes releases in the worker
  - loads refreshed catalog data in the worker
  - refreshes work manager/UI state before `100%`

- Unused album delete/purge now:
  - deletes in the worker
  - reloads refreshed lookup values in the worker
  - applies lookup/UI refresh before `100%`

## Architectural Notes

This patch follows the direction established by earlier progress handoffs rather than creating a second loader model:

- `true-progress-lifecycle-unification.md`
- `truthful-startup-profile-progress-reporting.md`
- `startup-profile-loading-and-task-progress-dialog-fix.md`
- `open-database-ui-thread-bottleneck-followup.md`

The key consistency decision here is:

- worker-safe service/database work lives in the bundle task
- widget/model/view refresh lives in `on_success_before_cleanup`
- logging/auditing/final follow-up messaging lives in `on_success_after_cleanup` where appropriate

That keeps the loader honest without moving unsafe widget work off-thread.

## QC Checks Performed

- audited real save/delete flows for works, tracks, and albums in the live repo
- confirmed the original blocking work was post-mutation UI hydration, not just the SQL write
- confirmed heavy safe work now runs through existing background bundle infrastructure
- confirmed UI-only work remains on the main thread
- confirmed the new add/delete flows use `on_success_before_cleanup` instead of early-complete `on_success`
- confirmed worker progress no longer emits `100%`
- confirmed `100%` is only emitted after final UI refresh
- confirmed the dialog only closes after the UI-ready step completes
- confirmed the previous `refresh_table_preserve_view()` duplicate blob-badge path remains removed

## QA Checks Performed

### Compile / sanity

- `python3 -m py_compile ISRC_manager.py isrc_manager/services/import_governance.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py tests/app/test_app_shell_workspace_docks.py tests/app/test_app_shell_profiles_and_selection.py`

### App-shell suites

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_profiles_and_selection`

### Infrastructure / focused regressions

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_task_manager`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_track_editor_save_succeeds_without_album_propagation`

### Additional focused reruns during bring-up

- work-manager governed-track save
- work-manager governed album launch/save
- delete-entry history visibility after async delete
- track-delete truthful-progress case

## Tests Added / Updated

### New truthful-progress regression coverage

Added architecture-level coverage in `tests/app/_app_shell_support.py` for:

- add-track save progress
- album save progress
- track delete progress
- work delete progress
- album cleanup/delete progress

These tests verify:

- background bundle submission is used
- `on_success_before_cleanup` is the UI-ready phase
- `on_success` is not used for these flows
- worker progress stays below `100%`
- UI progress reaches `100%` only at the final ready step

### Existing tests updated for real async completion

Updated save/delete tests to wait for background task completion before reading back DB/UI state, including:

- governed child track creation from Work Manager
- governed album creation paths
- add-track governance paths
- mixed-governance album batch path
- delete-entry visible-history assertion

### Re-exposed existing regression

- wired `case_track_editor_save_succeeds_without_album_propagation` into `tests/app/test_app_shell_editor_surfaces.py` so the now-refactored editor save path is actually exercised by the suite

## Known Edge Cases / Follow-Up Risks

- The final table/view hydration still happens on the main thread because widget mutation must remain main-thread-safe. The improvement here is that the expensive pre-hydration work is off-thread and the remaining main-thread phase now reports truthful UI progress while pumping events, rather than pretending the task is already complete.
- There are still other legacy flows in the application that call `refresh_table()` / `refresh_table_preserve_view()` synchronously outside this save/delete scope. Those were not changed here unless they were directly part of the affected work/track/album save paths.
- The new track editor orchestration is validated for the existing single-track non-propagating regression path. Bulk and propagated album-metadata saves now share the same runner, but there is not yet a dedicated progress-capture regression for those specific editor branches.

## Why This Does Not Regress Prior Logic

- It preserves the existing background task architecture and extends it consistently.
- It does not move widget mutation off the UI thread.
- It does not invent fake progress stages.
- It keeps history recording and audit/log behavior intact, just in more truthful lifecycle phases.
- It keeps the actual domain mutations in the same services/workflows while changing when and where the heavy refresh work is performed.

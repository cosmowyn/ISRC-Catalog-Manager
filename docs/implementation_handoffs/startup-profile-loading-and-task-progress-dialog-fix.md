# Startup / Profile Loading And Task Progress Dialog Fix

## Status And Scope

This is a targeted lifecycle and UI-state reliability fix.

Scope is intentionally limited to:

- startup readiness
- profile-switch readiness
- long-running task progress dialog geometry

No broader startup architecture, task architecture, or shell restructuring was introduced.

## Source Of Truth

Runtime files:

- `ISRC_manager.py`
- `isrc_manager/startup_progress.py`
- `isrc_manager/startup_splash.py`
- `isrc_manager/tasks/manager.py`

Tests:

- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_profiles_and_selection.py`
- `tests/test_task_manager.py`
- `tests/test_app_bootstrap.py`
- `tests/test_startup_splash.py`

## Confirmed Root Causes

### Early splash close / false-ready condition

- Startup readiness was split across two different lifecycles:
  - workspace geometry/dock restoration
  - catalog/workspace dataset hydration
- `startupReady` was emitted as soon as workspace restoration finished.
- The initial catalog refresh was still running afterward as a hidden background task, so the splash could close while the table was empty and the shell was still loading.
- Profile switching had the same problem in a different form:
  - the visible prepare-profile task dialog finished after DB preparation
  - `open_database()` and the catalog reload then continued after the visible dialog had already closed

### Unstable task dialog sizing / layout ownership

- Long-running export and tagging tasks all use the shared `QProgressDialog` created by `BackgroundTaskManager`.
- The dialog was being reconfigured on every progress and status update.
- `_configure_progress_dialog()` called `adjustSize()` and `resize()` repeatedly around changing label text.
- The dialog also forced an unnecessarily large cancel-button width, which could push the bottom row outside the effective content width on macOS.

## Loading Lifecycle Before Fix

### Startup

1. Bootstrap showed the splash.
2. `App.__init__` opened the database and kicked off `Load Catalog` in the background.
3. `showEvent()` triggered first-show workspace restoration.
4. `_restore_workspace_layout_on_first_show()` emitted `startupReady`.
5. Splash closed immediately.
6. Catalog hydration could still be running in the background, leaving the user with a half-ready shell and only the status-bar task hint.

### Profile Switch

1. Profile preparation ran as a visible background task dialog.
2. That dialog closed as soon as DB preparation finished.
3. `open_database()` then ran on the UI thread.
4. Catalog/workspace refresh started afterward as a hidden background task.
5. The shell could look frozen while only the bottom-left task hint remained visible.

## Loading Lifecycle After Fix

### Startup

1. Splash shows as before.
2. Initial catalog hydration is still started in the background, but it now reports back into startup readiness ownership.
3. Workspace restoration completes on first show.
4. If catalog hydration is still in flight, startup transitions to `Loading catalog…` instead of finishing.
5. Splash closes only after:
   - workspace restoration is complete
   - the startup catalog refresh has reached its terminal UI-applied state

### Profile Switch

1. Profile switching now creates runtime loading feedback using the existing splash controller when available.
2. That loading feedback remains visible through:
   - profile DB preparation
   - `open_database()`
   - catalog/workspace refresh
3. Catalog refresh completion now explicitly closes that loading feedback.
4. The history-driven profile-open path now uses the same background/profile lifecycle instead of bypassing it synchronously.

If the runtime splash asset is unavailable, profile switching still falls back to the existing managed task dialog path, but catalog refresh is still explicitly attached to the same completion boundary.

## Readiness Condition

Startup is now considered ready only when both are true:

- `_workspace_layout_restore_complete` is `True`
- the startup catalog refresh has completed its terminal UI lifecycle

For readiness, “catalog refresh complete” means:

- the background worker finished successfully and the dataset was applied to the UI
- or the refresh reached terminal failure and the user-facing error path completed

Profile switching uses the same terminal boundary:

- DB preparation finished
- `open_database()` completed
- the profile catalog refresh reached its terminal UI lifecycle

## Background Task Ownership And Coordination

- `_refresh_catalog_ui_in_background()` now has an explicit `on_complete` callback in addition to the existing success-only `on_finished`.
- Startup wires `catalog.ui.startup` into `on_complete`, so splash ownership now includes catalog hydration.
- Profile switching wires `catalog.ui.profile.*` into the same completion boundary, and the runtime loading splash is only finished from that callback.
- The hidden status-bar task hint still exists for ordinary background work, but it is no longer the only visible indicator during startup or profile-switch loading.

## Task Progress Dialog Root Cause

- The shared progress dialog was the correct owner, but its layout contract was unstable.
- Width and child sizing were being recalculated on every message/progress update.
- The dialog forced an oversized cancel button instead of using the native compact width.
- Combined with dynamic relayout, that allowed the bottom row to overflow horizontally and clip the action area.

## Task Progress Dialog Geometry Fix

- The shared `QProgressDialog` now computes one stable target width at creation time.
- That width is then preserved for the lifetime of the task.
- Labels still wrap, but only the dialog height is refreshed when task text changes.
- Progress-bar width now reserves explicit space for the button row instead of letting the content area consume it.
- Cancel buttons now use a compact fixed width derived from the native size hint rather than a large forced minimum.
- Result:
  - buttons remain fully visible
  - progress text updates no longer cause width thrash
  - the dialog remains visually stable during export/tag-writing progress updates

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/startup_progress.py`
- `isrc_manager/startup_splash.py`
- `isrc_manager/tasks/manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_profiles_and_selection.py`
- `tests/test_task_manager.py`
- `docs/implementation_handoffs/startup-profile-loading-and-task-progress-dialog-fix.md`

## Tests Added Or Updated

- Added startup coverage proving splash stays open until deferred catalog refresh completion.
- Added profile-switch coverage proving runtime loading feedback stays open until catalog reload completion.
- Extended task-manager coverage to assert:
  - stable fixed-width progress dialogs
  - action buttons remain inside the dialog bounds
  - width remains stable across multiple progress/message updates

Validation run:

- `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_profiles_and_selection tests.test_task_manager tests.test_app_bootstrap tests.test_startup_splash`
- `python3 -m black --check ISRC_manager.py isrc_manager/startup_progress.py isrc_manager/startup_splash.py isrc_manager/tasks/manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py tests/app/test_app_shell_profiles_and_selection.py tests/test_task_manager.py`

## Remaining Limitations Or Follow-Up

- Profile switching prefers the runtime splash controller when the splash asset is available. When it is not available, the fallback remains the managed task-dialog path rather than a custom replacement.
- This fix intentionally did not redesign `open_database()` or move more startup/profile work off the UI thread. It only corrected the readiness boundary and the visibility of the managed loading workflow.

## Exact Safe Pickup Instructions

1. Preserve the current readiness contract:
   - startup only finishes after workspace restore plus catalog refresh completion
   - profile switch only finishes after DB open plus catalog refresh completion
2. Do not reintroduce hidden catalog refresh work after splash/dialog dismissal.
3. Keep the shared `QProgressDialog` as the single long-running task dialog.
4. If future work needs broader startup or task architecture changes, treat that as a separate pass rather than folding it into this reliability fix.

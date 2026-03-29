# Saved Layout Switch Loading And Smooth Apply

## Previous behavior and hang source

Before this pass, saved-layout switching called `_apply_named_main_window_layout()` synchronously from both the saved-layout selector and the saved-layout menu. That meant the whole restore sequence ran on the UI thread with no managed loading dialog:

- load and resolve the named layout snapshot
- resolve Action Ribbon state
- ensure persistent dock shells
- restore geometry
- restore dock state or apply fallback panel visibility
- rebuild the Action Ribbon toolbar
- materialize visible lazy workspace docks
- persist the resulting layout state

The visible hang came from that entire stack happening inside the user interaction handler. The rough transition feel came from geometry, dock, and ribbon mutations repainting while the layout was still being rebuilt.

## UI-thread vs worker split

The switch now uses the existing managed background-task system instead of a second loader.

Moved off-thread:

- resolving the requested saved-layout payload from the stored layout collection
- validating that the named layout still exists
- deserializing saved geometry and dock-state payloads
- resolving Action Ribbon state from the saved snapshot, defaults, and legacy fallback rules

Kept on the UI thread:

- ensuring persistent dock shells
- applying main-window geometry
- restoring dock state
- applying fallback panel visibility when dock restore fails
- applying toolbar visibility and Action Ribbon configuration
- refreshing workspace dock placement flags
- materializing visible lazy dock panels
- persisting final geometry/dock/action-ribbon state
- final top-chrome refresh and control refresh

That split keeps QWidget mutations on the Qt GUI thread while still offloading the safe preparation work that can happen before the visible apply pass.

## Loading and progress lifecycle

Saved-layout switching now runs through `_submit_background_task(...)` with a dedicated `saved-layout-switch` unique key and a modal progress dialog.

The progress model is phase-based and tied to the real workflow:

1. Resolve saved layout payload
2. Prepare saved layout state
3. Prepare saved layout for restore
4. Apply saved geometry
5. Restore dock layout or fallback panel visibility
6. Apply toolbar and Action Ribbon state
7. Restore visible workspace panels
8. Persist restored layout state
9. Saved layout ready

During visible dock materialization, the loading label updates with the real dock/panel being restored, so the user sees the active substep instead of a generic busy message.

`100%` now corresponds to `9 / 9`, which is only emitted after the final layout state has been persisted and the window has been finalized.

## Repaint and reveal smoothing strategy

The restore flow now uses `_suspend_saved_layout_transition_updates()` during the heavy UI apply pass.

That helper temporarily disables updates on:

- the central widget
- dock widgets
- toolbars

This suppresses rough intermediate repainting while geometry, dock state, and ribbon state are being reapplied. After the restore pass finishes, updates are re-enabled, the app drains pending events, stops queued geometry/dock persistence timers, applies the top chrome boundary directly, and only then marks the progress dialog complete.

The selector and saved-layout menu no longer trigger the switch inline. Both entry points defer the background-task launch with `QTimer.singleShot(0, ...)` so the initiating UI interaction can settle before the toolbar/ribbon rebuild starts.

## Files changed

- `ISRC_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_layout_persistence.py`

## Tests added or updated

Added or updated app-shell coverage for:

- background-task-backed saved-layout switching from both selector and menu entry points
- truthful phase progress for saved-layout switching
- terminal completion only after final restore/finalization
- update-suppression usage during apply
- existing saved-layout persistence and Action Ribbon restore behavior

Validated with:

- `python3 -m unittest tests.app.test_app_shell_layout_persistence`
- `python3 -m unittest tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_saved_layouts_capture_and_restore_distinct_action_ribbon_configurations tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_deleting_saved_layout_removes_associated_action_ribbon_payload tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_legacy_saved_layouts_without_action_ribbon_state_load_safely`
- `python3 -m py_compile ISRC_manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_layout_persistence.py`
- `python3 -m black --check ISRC_manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_layout_persistence.py`
- `python3 -m ruff check tests/app/_app_shell_support.py tests/app/test_app_shell_layout_persistence.py`

## Remaining limitations / next bottlenecks

- The heaviest part of the switch is still visible-dock materialization, which must stay on the UI thread because it constructs and refreshes live widgets.
- Progress is truthful and phase-based, but dock-state restore itself is still a single Qt call, so there is no finer-grained internal progress available there.
- The restore path still depends on Qt’s `restoreState()` behavior for dock topology, so visual smoothness is improved by update suppression rather than by incremental dock animation.

## Explicit outcome

Saved-layout switching now uses a truthful managed loading/progress flow, keeps safe preparation work off-thread where possible, suppresses rough intermediate repainting during apply, and only reveals the final restored state once the layout switch is actually complete.

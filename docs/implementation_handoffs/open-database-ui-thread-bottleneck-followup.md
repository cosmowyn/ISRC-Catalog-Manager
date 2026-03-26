# Open Database UI-Thread Bottleneck Follow-Up

## Status And Scope

This is a focused follow-up to the completed startup/profile loading reliability fix.

Scope is intentionally limited to:

- the remaining `open_database()` bottleneck
- startup/profile-switch DB-open sequencing
- preserving the existing splash/dialog readiness contract

This pass does not redesign the broader startup architecture, background-task architecture, or catalog refresh lifecycle.

## Source Of Truth

Runtime:

- `ISRC_manager.py`

Tests:

- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_profiles_and_selection.py`
- `tests/test_app_bootstrap.py`
- `tests/test_startup_splash.py`
- `tests/test_migration_integration.py`

## Root Bottleneck Found

The main remaining bottleneck was not the live SQLite attach itself.

It was the repeated schema/bootstrap work surrounding it:

- startup called `open_database()` directly on the UI thread, which still ran `init_db()` and `migrate_schema()`
- profile switching already prepared the profile database in a background worker, but then `open_database()` repeated that same schema work again on the UI thread

That meant the app had a visible loading lifecycle, but still spent avoidable time inside the UI thread doing database preparation that had already been completed safely elsewhere.

## Open Database Sub-Steps

The current `open_database()` path breaks down into these parts:

1. close the previous live connection
2. open the live UI-thread SQLite session
3. assign `self.conn`, `self.cursor`, and `self.current_db_path`
4. configure background runtime against the active profile
5. build the live service graph
6. normalize/load profile artist code
7. persist profile-open bookkeeping
8. run schema init/migrations when needed
9. load readiness-critical profile state such as blob icon settings and active custom fields
10. refresh workspace/profile state that depends on the new live profile

## What Stayed On The UI Thread

These pieces still run on the UI thread because they own live app state or existing Qt/runtime objects:

- `_close_database_connection()`
- opening and assigning the live app session via `DatabaseSessionService.open()`
- `_configure_background_runtime()`
- `_init_services()`
- profile artist-code normalization/load
- loading `blob_icon_settings`
- loading `active_custom_fields`
- workspace dock refresh and the remaining post-open state refreshes

These steps remain inside the readiness boundary.

## What Moved Off-Thread

The worker-safe database preparation slice now owns:

- `init_db()`
- `migrate_schema()`
- migration audit logging for background-applied migrations

This worker preparation is now reused in two places:

- startup, before the live profile attach
- profile switching, before the live profile attach

After worker preparation succeeds, the UI-thread `open_database()` call now runs with `schema_prepared=True`, so it skips the duplicate schema/bootstrap pass.

## What Was Deferred

This pass intentionally did not defer larger chunks of post-open work.

In particular, it did not defer:

- active custom-field loading
- blob icon settings loading
- workspace/profile state refreshes
- catalog refresh ownership

Those still participate in the readiness contract because the shell depends on them before it is truly ready.

## Readiness Contract After The Fix

The readiness contract from the previous pass is preserved.

Startup is still only ready after:

- workspace restoration completes
- startup catalog refresh reaches terminal UI completion

Profile switching is still only ready after:

- database preparation finishes
- the selected profile is attached through `open_database()`
- profile catalog refresh reaches terminal UI completion

No hidden post-ready catalog initialization was reintroduced.

## Lifecycle Change Summary

### Startup Before

1. splash opened
2. `open_database()` ran full schema/bootstrap work on the UI thread
3. shell built
4. catalog refresh started
5. readiness waited for workspace restore + catalog refresh

### Startup After

1. splash opens
2. profile database preparation runs in a background task
3. startup waits for that preparation to finish
4. `open_database(..., schema_prepared=True)` attaches the live profile on the UI thread
5. shell builds
6. catalog refresh starts
7. readiness still waits for workspace restore + catalog refresh

### Profile Switch Before

1. background prepare task ran `init_db()` / `migrate_schema()`
2. task finished
3. `open_database()` reran `init_db()` / `migrate_schema()` on the UI thread
4. catalog refresh started

### Profile Switch After

1. background prepare task runs `init_db()` / `migrate_schema()`
2. task finishes
3. `open_database(..., schema_prepared=True)` attaches the live profile without repeating schema work
4. catalog refresh starts

## Files Changed

- `ISRC_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_profiles_and_selection.py`

## Tests Added Or Updated

- updated startup phase-order coverage to reflect background DB preparation before live service loading
- added startup coverage proving startup uses the prepared open path
- added profile-switch coverage proving activation reuses the prepared open path
- added direct coverage proving `open_database(..., schema_prepared=True)` skips `init_db()` and `migrate_schema()`

Validation run:

- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m unittest tests.app.test_app_shell_profiles_and_selection`
- `python3 -m unittest tests.test_app_bootstrap tests.test_startup_splash`
- `python3 -m unittest tests.test_migration_integration`
- `python3 -m black --check ISRC_manager.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py tests/app/test_app_shell_profiles_and_selection.py`

## Remaining Limitations Or Next Bottlenecks

- `open_database()` still performs live service construction on the UI thread.
- `active_custom_fields` and related per-profile UI state are still loaded synchronously because they are currently readiness-critical.
- Startup still waits synchronously for worker preparation via a nested event loop; this is acceptable for the current targeted fix because the visible loading lifecycle stays owned correctly, but a broader redesign would be a separate pass.

## Exact Safe Pickup Instructions

1. Preserve the `schema_prepared=True` path for any future caller that has already completed worker-side database preparation.
2. Do not move live connection assignment or Qt/UI-owned state into worker threads.
3. Keep startup/profile readiness attached to the existing splash/dialog lifecycle.
4. If future work tries to reduce startup cost further, treat service-graph slimming and post-ready warmups as a separate pass rather than folding them into this follow-up.

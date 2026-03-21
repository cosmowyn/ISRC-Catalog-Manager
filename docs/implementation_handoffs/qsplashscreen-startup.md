# QSplashScreen Startup Handoff

## Purpose

This document describes the current startup/splash contract for the desktop app.

The startup follow-up removed these former limitations:

- splash lifecycle no longer depends on a private `QApplication` attribute
- splash progress is no longer text-only; it is now milestone-based and truthful
- startup migration dialogs and schema-migration error dialogs no longer compete with a visible splash
- direct `App()` construction now has an explicit startup-feedback path
- the build path now uses one splash strategy only: the runtime `QSplashScreen`

## Source Of Truth

- Runtime entrypoint and bootstrap:
  - [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
  - [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
- Splash controller and startup phases:
  - [`isrc_manager/startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/startup_splash.py)
  - [`isrc_manager/startup_progress.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/startup_progress.py)
- Shell composition and workspace restore dependencies:
  - [`isrc_manager/main_window_shell.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/main_window_shell.py)
  - [`docs/implementation_handoffs/workspace-layout-persistence-handoff.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/workspace-layout-persistence-handoff.md)
- Storage migration dependency:
  - [`docs/implementation_handoffs/storage-migration-reliability-fix.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-migration-reliability-fix.md)
- Packaging:
  - [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py)
- Regression coverage:
  - [`tests/test_app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_bootstrap.py)
  - [`tests/test_startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_startup_splash.py)
  - [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)
  - [`tests/test_build_requirements.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_build_requirements.py)

## Startup Lifecycle Contract

The real entrypoint is still `ISRC_manager.main()`, which delegates to `run_desktop_application()`.

Current ordered startup flow:

1. `init_settings()`
2. `_install_qt_message_filter()`
3. `get_or_create_application()`
4. `enforce_single_instance()`
5. create and show the splash in [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
6. set the splash to the `STARTING` phase
7. construct `App(startup_feedback=splash)`
8. show the main window
9. process Qt events once so first-show restore can run before `app.exec()`
10. finish the splash when `App.startupReady` fires
11. keep a final cleanup fallback in bootstrap `finally`

The finish boundary is still the same: splash completion happens only after `_restore_workspace_layout_on_first_show()` completes and emits `startupReady`.

## Progress Reporting

Startup progress is milestone-based and phase-driven. It is not time-based and it does not attempt fine-grained pseudo-progress.

Current startup milestones:

- `STARTING` = `5`
- `RESOLVING_STORAGE` = `15`
- `INITIALIZING_SETTINGS` = `30`
- `OPENING_PROFILE_DB` = `45`
- `LOADING_SERVICES` = `55`
- `PREPARING_DATABASE` = `70`
- `FINALIZING_INTERFACE` = `85`
- `RESTORING_WORKSPACE` = `95`
- `READY` = `100`

Who emits phases:

- bootstrap emits `STARTING`
- `App.__init__()` emits storage/settings/profile/interface phases
- `open_database()` emits `LOADING_SERVICES` and `PREPARING_DATABASE`
- `_restore_workspace_layout_on_first_show()` emits `RESTORING_WORKSPACE`
- `complete_startup_feedback()` emits `READY` immediately before finish

What changed:

- the splash now keeps phase text and a determinate progress bar
- the longest database-startup blind spot is split by `PREPARING_DATABASE`
- startup remains synchronous for migration, database, shell, and restore correctness

What did not change:

- background catalog loading is still not part of splash readiness
- `startupReady` still means “main window restored and ready,” not “all lazy/background work complete”

## Dialog Coordination

Startup-critical dialogs now run through a startup-modal helper in `App`.

Behavior:

- suspend and hide the splash before showing a startup modal dialog
- drain events so the splash is no longer visually competing
- show a `QMessageBox` instance with `Qt.ApplicationModal`
- use `self` as parent only when the main window is visible; otherwise use no parent
- resume and repaint the last splash phase after the dialog closes if startup is continuing

Dialog paths covered:

- storage migration prompt during `_reconcile_startup_storage_root()`
- startup storage migration failure warning
- startup storage migration success information dialog
- schema migration error dialog from `open_database()`

This preserves existing migration decision semantics while making the dialog the only active startup UI during the blocking step.

## Direct `App()` Construction

Direct callers now have an explicit splash/startup-feedback path.

Supported patterns:

- bootstrap path: `run_desktop_application()` creates the splash and passes it into `App(startup_feedback=...)`
- direct path: tests/scripts may also construct `App(startup_feedback=controller)` explicitly

Important behavior:

- `App` stores the feedback object on the instance, not on `QApplication`
- `App.startupReady` is connected to `complete_startup_feedback()`
- `complete_startup_feedback()` finishes the feedback object once and then clears it
- if a direct caller never shows the window, `startupReady` will not fire; that caller may call `complete_startup_feedback()` manually if it opted into splash behavior

This is the supported replacement for the old private `_startup_splash_controller` wiring.

## Responsiveness Changes

Safe responsiveness improvements in this pass:

- help-file generation was removed from `App.__init__` and remains lazy at the existing help entry points
- the initial generated-ISRC preview refresh moved to a post-ready idle tick
- the new `PREPARING_DATABASE` milestone adds an extra event-drain boundary during startup

Intentional non-changes:

- storage migration stays synchronous
- `open_database()`, schema migration, and service initialization stay on the critical path
- workspace restore and persistent dock-shell creation stay on the current side of `startupReady`
- no startup-critical work was moved to background threads

## Splash Asset And Packaging Contract

Runtime splash asset lookup is unchanged:

- runtime lookup still resolves `RES_DIR()/build_assets/splash.*`
- `build_assets/splash.*` remains the packaged runtime asset contract
- missing asset or invalid image still returns `None` and startup continues without a splash

Build behavior changed:

- PyInstaller bootloader `--splash` was removed from [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py)
- the runtime splash asset is still bundled through `--add-data`
- packaged builds now use only the app-side `QSplashScreen`

This is the single-splash strategy on all platforms, including macOS.

## Regression Coverage

Updated coverage now verifies:

- bootstrap still creates the splash after the single-instance lock and before window construction
- the splash controller handles progress, suspend/resume, event draining, and idempotent finish
- direct `App(startup_feedback=...)` startup reaches the expected ordered milestones and auto-finishes on `startupReady`
- startup migration dialog flows suspend the splash while the dialog is active
- startup schema-migration errors also suspend the splash while the dialog is active
- build command generation no longer emits PyInstaller `--splash`
- runtime splash asset bundling still uses `--add-data`

Targeted verification command:

- `python3 -m unittest tests.test_app_bootstrap tests.test_startup_splash tests.test_app_shell_integration tests.test_storage_migration_service tests.test_migration_integration tests.test_build_requirements`

## Remaining Limitations

- Startup-critical work is still mostly synchronous by design; the progress bar is phase-based, not elapsed-time-based.
- Background catalog loading still begins after startup shell construction and is not part of the ready boundary.
- The splash progress bar is only as granular as the explicit startup milestones; it does not report internal loop-by-loop migration or schema progress.

## Future Follow-Up

- Profile the shell-build and workspace-restore path if startup feels slow on large saved layouts.
- Keep any future startup deferrals limited to clearly non-critical UI/data warmup.
- If a future pass needs deeper progress granularity, add it only where a real stable milestone exists.

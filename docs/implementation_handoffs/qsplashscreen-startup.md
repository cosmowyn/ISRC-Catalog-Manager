# QSplashScreen Startup Handoff

Current product version: `2.0.0`

Date: 2026-03-20

## Status

This pass adds a Qt-native startup splash using `QSplashScreen`.

Scope boundaries for this pass:

- no broader startup redesign
- no threaded loader or animated custom splash window
- no business-logic changes outside startup status reporting
- no change to storage migration policy, profile selection semantics, workspace restore rules, or background bootstrap behavior

## Source Of Truth

- Runtime entrypoint and startup phases:
  - [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
  - [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
- Runtime asset resolution:
  - [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py)
  - [`isrc_manager/startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/startup_splash.py)
- Packaging:
  - [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py)
- Tests:
  - [`tests/test_app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_bootstrap.py)
  - [`tests/test_startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_startup_splash.py)
  - [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)
  - [`tests/test_build_requirements.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_build_requirements.py)

## Startup Insertion Point

The real entrypoint is still `ISRC_manager.main()`, which delegates to `run_desktop_application()`.

Current startup order after this pass:

1. `init_settings()`
2. `_install_qt_message_filter()`
3. `get_or_create_application()`
4. `enforce_single_instance()`
5. create and show the splash in [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
6. construct `App()`
7. show the main window
8. process Qt events once so first-show restore can run
9. finish the splash when `App.startupReady` fires
10. enter `app.exec()`

This keeps the splash as early as possible without showing it on the duplicate-instance early-exit path.

The finish boundary is not `showMaximized()` alone. The splash is closed only after [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py) completes `_restore_workspace_layout_on_first_show()` and emits `startupReady`.

## Splash Asset Resolution

The splash asset now resolves through [`isrc_manager/startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/startup_splash.py):

- candidate root is `RES_DIR()`
- candidate folder is `build_assets/`
- filename convention is `splash.*`
- extension order is:
  - `.png`
  - `.jpg`
  - `.jpeg`
  - `.bmp`
  - `.gif`

Current repo asset:

- [`build_assets/splash.png`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build_assets/splash.png)

Behavior by environment:

- dev/source run:
  - `RES_DIR()` resolves to the repo root, so the splash loads from `build_assets/splash.*`
- packaged run:
  - `RES_DIR()` resolves to bundled read-only resources, so the same lookup works without hardcoding bundle internals

Fallback behavior:

- if no candidate exists, splash creation returns `None`
- if the image exists but `QPixmap` cannot load it, splash creation returns `None`
- startup still continues normally in both cases

## Status Messaging

The splash status path is intentionally narrow.

Bootstrap creates a temporary controller and stores it on `QApplication` under a private attribute. `App._report_startup_status()` looks up that controller and no-ops when the splash is absent.

Real startup phases now reported:

- `Starting application…`
  - emitted in [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py) immediately after the splash is shown
- `Resolving storage layout…`
  - emitted before `_reconcile_startup_storage_root()`
- `Initializing settings…`
  - emitted before identity/theme/help bootstrap
- `Opening profile database…`
  - emitted just before `open_database(last_db)`
- `Loading services…`
  - emitted inside `open_database()` after opening the DB session and before `_init_services()`
- `Finalizing interface…`
  - emitted before shell composition, persistent dock shells, saved view preferences, and theme application
- `Restoring workspace…`
  - emitted at the start of `_restore_workspace_layout_on_first_show()`

Responsiveness behavior:

- the splash controller calls `processEvents()` after `show()`
- it also calls `processEvents()` after each `showMessage()` update
- bootstrap calls `processEvents()` once after the main window show call so the first-show restore timer can run before `app.exec()`

## Packaging / Runtime Notes

This pass complements, but does not replace, the build script’s existing PyInstaller splash handling.

Current packaging behavior in [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py):

- bootloader `--splash` still uses `build_assets/splash.*`
- bootloader `--splash` is still skipped on macOS
- the runtime splash asset is now bundled separately with `--add-data`

Why this matters:

- PyInstaller boot splash and app-side `QSplashScreen` are separate mechanisms
- macOS was already skipping PyInstaller splash, so the in-app `QSplashScreen` is the macOS-safe startup path
- runtime loading now depends on `RES_DIR()` rather than repo-relative paths or manual `_MEIPASS` logic

The build script now keeps both bootloader splash resolution and runtime splash bundling aligned to the same `build_assets/splash.*` naming convention.

## Tests Added Or Updated

Updated:

- [`tests/test_app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_bootstrap.py)
  - verifies splash creation happens after the lock succeeds
  - verifies splash show/status happen before `window_factory()`
  - verifies splash finish is deferred until the ready-signal path
  - verifies duplicate-instance early exit does not call splash setup
- [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)
  - verifies real startup phase messages
  - verifies finish happens only after `show()` plus event draining
- [`tests/test_build_requirements.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_build_requirements.py)
  - verifies runtime splash asset bundling through `--add-data`
  - keeps existing non-macOS bootloader `--splash` behavior
  - keeps macOS bootloader splash skipped

Added:

- [`tests/test_startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_startup_splash.py)
  - runtime asset preference order
  - missing-asset fallback
  - invalid-image fallback
  - valid-controller creation and basic lifecycle calls

Targeted verification run:

- `python3 -m unittest tests.test_app_bootstrap tests.test_startup_splash tests.test_app_shell_integration tests.test_build_requirements`

## Remaining Limitations / Follow-Up

- Startup is still mostly synchronous. The splash improves visibility and responsiveness, but it does not make heavy work asynchronous.
- Storage migration prompts and startup migration-error dialogs can still take foreground focus during startup. That is expected and intentionally preserved.
- There is still no percentage indicator or progress bar. This pass uses stable phase messages only.
- Direct `App()` construction in tests or scripts does not automatically finish a splash, because the bootstrap wiring lives in `run_desktop_application()`. That is intentional so the entrypoint remains the authoritative startup path.

## Reference Appendix

Key runtime files:

- [`isrc_manager/startup_splash.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/startup_splash.py)
- [`isrc_manager/app_bootstrap.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_bootstrap.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`build.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build.py)

Key asset:

- [`build_assets/splash.png`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/build_assets/splash.png)

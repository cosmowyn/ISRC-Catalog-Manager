# Build.py Robustness Alignment Handoff

Date: 2026-03-21

## Why `buildfile.py` Was Succeeding More Often

The original `build.py` was intentionally strict, but that strictness made common local Windows builds brittle in ways the reference `buildfile.py` was not.

The main gaps were:

- `build.py` only verified PyInstaller through `python -m PyInstaller` using `sys.executable`
- Windows users with a working repo-local `.venv\Scripts\pyinstaller.exe` still failed if PyInstaller was not installed into the exact interpreter running `build.py`
- asset lookup assumed only the current canonical `build_assets/` layout
- entry-script validation was a simple existence check with limited diagnostics
- converted icons were written into `build/generated_assets/`, but the old flow cleaned `build/` after asset resolution, which could delete a freshly converted icon before PyInstaller ran

The reference `buildfile.py` succeeded more often because it tolerated repo-local Windows PyInstaller installs and older fallback asset layouts.

## Robustness Gaps Closed In `build.py`

`build.py` now keeps the canonical repo layout as first priority, but adds deterministic fallback behavior and clearer diagnostics.

Closed gaps:

- Windows PyInstaller discovery now tries the repo-local executable first, then the current interpreter module, then a `PATH` fallback
- each PyInstaller candidate is verified with `--version` before use
- failure output now shows exactly what was tried and why each option failed
- icon lookup now prefers `build_assets/icons/` but falls back to `resources/` and repo root
- splash lookup now prefers `build_assets/` but falls back to `resources/` and repo root
- entry-script resolution now emits strong diagnostics when `ISRC_manager.py` is missing and explicitly mentions `main.py` if present
- cleanup now happens before icon resolution so generated converted icons are not deleted before the build

## Final PyInstaller Discovery Order

### Windows

1. `PROJECT_ROOT/.venv/Scripts/pyinstaller.exe`
2. `sys.executable -m PyInstaller`
3. `pyinstaller` from `PATH`

The first candidate that passes `--version` is used for the real build command.

### macOS and Linux

1. `sys.executable -m PyInstaller`

No `PATH` fallback was added on non-Windows so the script stays conservative there.

## Final Asset Resolution Priority

### Icon resolution

Location priority:

1. `build_assets/icons/`
2. `resources/`
3. repo root

Basename priority within each location:

1. `app_logo`
2. `icon`

Extension priority:

- Windows: `.ico`, `.png`, `.jpg`, `.jpeg`, `.bmp`
- macOS: `.icns`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.gif`
- Linux: `.png`, `.ico`, `.icns`

Conversion behavior:

- Windows converts a selected non-`.ico` icon into `build/generated_assets/icons/app_logo.ico`
- macOS converts a selected non-`.icns` icon into `build/generated_assets/icons/app_logo.icns`
- Linux uses the selected file directly

If no icon is found, the build continues without `--icon` and prints a non-fatal diagnostic.

### Splash resolution

Priority order:

1. `build_assets/splash.{png,jpg,jpeg,bmp,gif}`
2. `resources/splash.{png,jpg,jpeg,bmp,gif}`
3. repo-root `splash.{png,jpg,jpeg,bmp,gif}`

The packaged runtime contract is unchanged:

- the splash asset is still bundled with `--add-data ... build_assets`
- runtime lookup still expects `build_assets/splash.*`

If no splash is found, the build continues without bundling a splash asset.

## Entry-Script Resolution And Diagnostics

`ISRC_manager.py` remains the only canonical entry script.

Behavior now:

- `_resolve_entry_script()` requires `PROJECT_ROOT/ISRC_manager.py`
- if that file is missing, the build fails before PyInstaller discovery
- the error reports the expected path, current working directory, project root, and nearby top-level `*.py` files
- `main.py` is explicitly called out as a legacy-looking candidate if it exists
- no automatic fallback entry script is selected

## Tests Added And Updated

Updated test module:

- `tests/test_build_requirements.py`

Coverage added or updated for:

- Windows PyInstaller discovery preferring `.venv/Scripts/pyinstaller.exe`
- Windows fallback to `python -m PyInstaller`
- clean failure when every Windows PyInstaller candidate fails
- canonical icon resolution winning over fallback locations
- Windows fallback icon conversion from `resources/icon.png`
- macOS fallback icon conversion from repo-root `icon.png`
- canonical splash resolution winning over fallbacks
- fallback splash resolution from `resources/splash.png`
- fallback splash resolution from repo-root `splash.png`
- missing splash remaining non-fatal
- missing entry script producing strong diagnostics
- command generation preserving existing onefile/onedir behavior while honoring the selected PyInstaller launcher
- main-flow cleanup happening before icon resolution

Validation run:

- `python3 -m unittest tests.test_build_requirements`

## Remaining Limitations And Future Cleanup Recommendations

- `build.py` still does not auto-switch to `main.py`; that is intentional to keep the repo’s canonical entrypoint explicit
- no env-var asset override was added in this pass, to avoid changing precedence and packaged runtime behavior
- non-Windows platforms still require PyInstaller in the current interpreter
- the fallback asset paths are compatibility aids; once older local layouts are no longer needed, the repo can simplify back toward canonical `build_assets/` only

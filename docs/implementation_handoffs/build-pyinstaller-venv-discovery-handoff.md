# Build PyInstaller Venv Discovery Handoff

Current product version: `3.2.0`

Date: 2026-04-17

## Root-Cause Analysis

- `build.py` originally assumed the active interpreter was the right build interpreter, which broke after venv refreshes or when the script was launched from another Python on the machine.
- The first fallback change added repo-local and parent-directory venv probing, but it resolved `.venv/bin/python` on macOS/Linux. That collapsed the venv symlink back to the framework Python and escaped the virtual environment.
- PyInstaller discovery still preferred `python -m PyInstaller` on non-Windows platforms, which remained fragile under debugger launchers and mixed interpreter setups.
- When a launcher printed `No module named PyInstaller`, the script could still continue into the generic missing-artifact path instead of failing at the real cause.

## What Changed

- Added ordered venv probing for both Python and PyInstaller launchers:
  - `project_root/.venv`
  - `project_root.parent/.venv`
  - current interpreter module fallback
  - PATH fallback for `pyinstaller`
- Preserved the venv launcher path itself instead of resolving `.venv/bin/python` symlinks back to the base interpreter.
- Unified PyInstaller discovery across platforms so macOS/Linux now prefer the repo-local venv executable (`.venv/bin/pyinstaller`) before trying `python -m PyInstaller`.
- Expanded discovery errors to show the ordered launcher search path for both Windows and non-Windows builds.
- Added an explicit missing-module output guard so `No module named PyInstaller` stops the build with an `ERROR [build]` result instead of the misleading artifact-missing `SystemExit(2)` path.

## Files Touched

- `build.py`
- `tests/test_build_requirements.py`

## Regression Coverage

Added or updated coverage for:

- repo-local venv Python selection before the parent-directory venv
- parent-directory venv Python fallback
- symlink-preserving repo-local venv Python resolution on macOS/Linux
- repo-local POSIX `pyinstaller` launcher preference
- parent-directory Windows `pyinstaller.exe` fallback
- early stop when the build launcher output reports `No module named PyInstaller`

## Validation

- `./.venv/bin/python -m unittest tests.test_build_requirements -v`
- `python3 - <<'PY' ... build._select_pyinstaller(...) ... PY`
  - confirmed launcher selection resolves to `.../.venv/bin/pyinstaller`
- `python3 build.py`
  - smoke-checked until the corrected launcher and command were printed
  - interrupted before waiting for a full packaged artifact to finish

## Remaining Limitations

- This pass improves launcher discovery and failure reporting only; it does not change PyInstaller spec generation, artifact naming, or bundle contents.
- The packaging flow still depends on a working local PyInstaller install in either the repo-local venv, the parent-directory venv, or PATH.
- The final smoke run verified the corrected launcher path but did not wait for a complete `.app` build artifact.

## Follow-Up Guidance

- If future build automation wraps `build.py` from editors or task runners, prefer launching it from any interpreter; the script should now self-correct onto the repo-local venv launcher.
- If another PyInstaller lookup issue appears, inspect the printed `pyinstaller launcher` and `pyinstaller verify` diagnostics first before changing artifact logic.
- Keep any custom private branding assets out of the build-script commits unless they are intentionally part of the shared repo state.

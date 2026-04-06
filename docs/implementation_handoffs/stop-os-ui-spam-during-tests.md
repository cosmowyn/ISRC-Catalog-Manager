# Stop OS UI Spam During Tests

## 1. Remaining launch root causes found

- The repository already had a partial central launcher in `isrc_manager/external_launch.py`, but the suite bootstrap was not authoritative. The prior guard depended mainly on `tests/__init__.py` and `tests/qt_test_helpers.py`, which `python -m unittest discover -s tests ...` can bypass by importing top-level modules like `test_task_manager` instead of `tests.test_task_manager`.
- Direct chooser dialogs were outside the central safety layer. App code still used `QFileDialog.getOpenFileName`, `getSaveFileName`, and `getExistingDirectory` directly in many places, so a GUI test could still spawn real chooser UI even if external URL/file opening was blocked.
- The macOS Pages bridge in `isrc_manager/contract_templates/ingestion.py` still launched Pages through raw `subprocess.run([osascript], input=...)`. Tests stayed quiet only when the subprocess heuristics happened to recognize that AppleScript as a launcher.
- The existing blocking covered `QDesktopServices`, `webbrowser`, and several subprocess APIs, but the real fix point needed to be the process bootstrap plus the remaining bypass seams, not more one-off test monkeypatches.

## 2. Seams centralized

- Kept `isrc_manager/external_launch.py` as the single authoritative desktop-integration policy module.
- Added `run_external_launcher_subprocess(...)` for explicit desktop-app launch subprocesses that are legitimate runtime behavior but must be blocked and recorded in tests.
- Routed the Pages AppleScript export path through that helper instead of raw `subprocess.run(...)`.
- Extended the installed test guard so `QFileDialog` static chooser entrypoints are intercepted centrally instead of relying on per-test patches.

## 3. Test-mode blocking strategy

- `install_test_process_desktop_safety()` now enables the full suite guard:
  - blocks `QDesktopServices.openUrl(...)`
  - blocks `webbrowser.open(...)`
  - blocks launcher subprocess calls such as macOS `open`, AppleScript app launches, and `os.system("open ...")`
  - blocks `QFileDialog` static chooser dialogs by returning immediate cancel values
  - enables `Qt.AA_DontUseNativeDialogs` before Qt app startup when possible
- Bootstrap is now layered so it is difficult to miss:
  - repo-root `sitecustomize.py`
  - `tests/sitecustomize.py`
  - `tests/__init__.py`
  - `tests/qt_test_helpers.py`
  - `tests/run_module.py`
  - `tests/run_group.py`
  - `isrc_manager/external_launch.py` import-time auto-install for test-looking processes
  - `unittest` discovery/load hook so top-level `unittest discover` GUI modules are protected before execution

## 4. How launch intents are recorded

- Blocked desktop interactions are recorded through the same history mechanism in `isrc_manager/external_launch.py`.
- Recorded entries capture:
  - `via`
  - `target`
  - `blocked`
  - `source`
  - metadata such as command text, shell mode, dialog caption/directory, or integration type
- Tests can inspect the recorded attempts with `get_recorded_external_launches()` and reset state with `clear_recorded_external_launches()`.

## 5. Runtime behavior preservation

- Outside test processes, real runtime behavior is preserved.
- `open_external_url(...)` and `open_external_path(...)` still delegate to the real `QDesktopServices` behavior.
- The Pages adapter still performs the real Pages export in production; it now does so through the central helper instead of bypassing the policy with raw subprocess execution.
- The chooser-dialog interception only exists when the test desktop-safety guard is installed.

## 6. Tests added/updated

- Updated `tests/test_external_launch.py` to cover:
  - local `file:` URL blocking
  - `QFileDialog` chooser blocking and recording
  - `subprocess.run(..., shell=True)` with macOS `open`
  - AppleScript chooser blocking
  - central `run_external_launcher_subprocess(...)` blocking and recording
  - a negative-control subprocess that must not be blocked
  - a child `unittest discover` probe that proves top-level GUI modules are protected by default
- Added `tests/test_desktop_safety_probe.py` as a top-level discovery sentinel that does not import `tests.*` and asserts:
  - test blocking is active
  - native dialogs are disabled
  - `QDesktopServices` is blocked and recorded
  - `QFileDialog` is blocked and cancelled
- Updated `tests/contract_templates/test_scanner.py` so the Pages adapter tests follow the new central helper and added a regression that proves the real adapter path records launch intent instead of launching Pages during tests.

## 7. Risks and caveats

- The guarantee is anchored to the repository-supported automated runners and import paths:
  - `python -m unittest ...`
  - `python -m tests.run_module ...`
  - `python -m tests.run_group ...`
- A bare file-path script launch outside the repo import model can still fail before any repo bootstrap if Python cannot import `isrc_manager` at all. That is an import-path problem, not an external-launch leak in the supported suite runners.
- CLI-only subprocesses such as `ffmpeg`, `ffprobe`, and `textutil` are intentionally not blocked because they are not desktop-app launch paths.

## 8. Explicit final statement

The automated test suite no longer spawns OS UI, Dock spam, browser/Finder/Preview handoff, chooser dialogs, or external apps through the repository’s supported test runners. External-launch intent remains observable in tests, while real production/runtime desktop behavior remains intact outside tests.

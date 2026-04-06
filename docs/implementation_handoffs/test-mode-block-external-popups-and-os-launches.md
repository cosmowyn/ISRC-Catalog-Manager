# Test-Mode External Launch Blocking

## Summary
- Automated tests now run with a suite-wide no-external-launch policy enabled before test modules execute.
- External launch attempts are intercepted centrally, recorded for assertions, and blocked from reaching macOS Launch Services, browsers, Finder, App Chooser dialogs, or other desktop apps.
- Runtime behavior outside tests is preserved by delegating through the original launcher implementations when blocking is disabled.

## Popup-Spam Root Causes Found
- Direct `QDesktopServices.openUrl(...)` calls bypassed the test harness in the main window, contract documents, and contract template workspaces.
- The contract template preview page handed non-local main-frame navigation straight to `QDesktopServices`, which left test runs vulnerable to external browser/app launches.
- `HelpContentsDialog` used `QTextBrowser.setOpenExternalLinks(True)`, which allowed widget-driven external link handling to bypass test seams.
- macOS Pages conversion uses `osascript` with `tell application "Pages"` and `open ...`; without a central guard, tests could still trigger external application launches through subprocess.

## External-Launch Seams Audited
- `QDesktopServices.openUrl(...)`
- `webbrowser.open(...)`, `open_new(...)`, `open_new_tab(...)`
- macOS/desktop launcher subprocess paths such as `open`, `xdg-open`, `explorer`, `cmd /c start`, PowerShell `Start-Process`, and `osascript`
- Widget-driven external link behavior in `HelpContentsDialog`
- `QWebEnginePage.acceptNavigationRequest(...)` in the contract template HTML preview

## Central Launch Policy / Abstraction Chosen
- Added [`isrc_manager/external_launch.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/external_launch.py) as the single external-launch policy layer.
- Public helpers:
  - `open_external_url(...)`
  - `open_external_path(...)`
  - `install_test_external_launch_guard(...)`
  - `get_recorded_external_launches()`
  - `clear_recorded_external_launches()`
  - `temporary_external_launch_blocking(...)`
- The module preserves original runtime delegates internally and patches the desktop-launch seams only when the test guard is enabled.

## How Test Mode Blocks OS Launches
- The test package bootstrap in [`tests/__init__.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/__init__.py) sets `ISRC_MANAGER_BLOCK_EXTERNAL_LAUNCHES=1` and installs the guard automatically.
- `tests/qt_test_helpers.py` also installs the guard idempotently when `QApplication` is requested, so Qt-heavy tests stay protected even when bootstrapped differently.
- In guarded mode:
  - `QDesktopServices.openUrl(...)` is patched to record and no-op safely.
  - `webbrowser` launch helpers are patched to record and no-op safely.
  - launcher-like subprocess invocations are patched to record and return safe success shims instead of reaching the OS.
- macOS-specific `osascript` launches are detected both from command arguments and from AppleScript supplied through stdin.

## How Launch Intents Are Recorded
- Every intercepted launch attempt is stored as an `ExternalLaunchRequest` with:
  - `via`
  - `target`
  - `blocked`
  - `source`
  - `metadata`
- Tests can inspect recorded launch intents through `get_recorded_external_launches()` and clear them with `clear_recorded_external_launches()`.

## Runtime Paths Rewired
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
  - `_open_local_path(...)`
  - PDF preview external fallback
- [`isrc_manager/contracts/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contracts/dialogs.py)
  - `open_selected_document()`
- [`isrc_manager/contract_templates/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py)
  - preview-page external navigation
  - fill-tab latest PDF open
  - admin artifact open
- [`isrc_manager/app_dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/app_dialogs.py)
  - `HelpContentsDialog` now routes external anchors through the central helper instead of implicit `QTextBrowser` desktop launching

## Tests Added / Updated
- Added [`tests/test_external_launch.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_external_launch.py) covering:
  - suite bootstrap activation
  - direct `QDesktopServices` blocking/recording
  - `webbrowser` blocking/recording
  - macOS `open` command blocking/recording
  - macOS `osascript` Pages-launch blocking/recording
  - widget-driven external help-link interception
  - runtime allow-mode delegation
- Updated [`tests/contract_templates/test_dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_dialogs.py) to:
  - keep `data:` preview navigation internal
  - assert external preview navigation is routed through the central guard and recorded

## Risks / Caveats
- The subprocess guard intentionally targets launcher-like commands only; ordinary background tools and conversions continue to run in tests unless they match the guarded desktop-launch patterns.
- Tests that intentionally want real external launches must explicitly disable blocking with `temporary_external_launch_blocking(False)`.
- `ISRC_manager.py` still contains pre-existing repo-wide lint debt unrelated to this pass; the new launcher work was kept narrow rather than mixing in unrelated monolith cleanups.

## Final Outcome
- Automated tests no longer spawn OS popup windows, external application choosers, browsers, Finder windows, or similar desktop applications.
- External-open intent is still observable and assertable in tests through the recorded launch history.
- Production and normal developer runtime behavior remain intact outside test mode.

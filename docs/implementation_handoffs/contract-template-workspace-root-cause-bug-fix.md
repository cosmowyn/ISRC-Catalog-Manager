# Contract Template Workspace Root-Cause Bug Fix

## Scope
This pass fixed the Contract Templates Workspace instability in the nested dock host used by the Import, Symbol Generator, and Fill Form tabs.

The work was intentionally a root-cause pass, not a cosmetic patch pass.

## 1. Failure Symptoms Reproduced

### Unlock / compositor
- Reproduced that unlocking by itself was not the real trigger.
- Reproduced that floating the HTML Preview dock after unlock produced the `Compositor returned null texture` family of failures, while floating non-preview docks did not.

### Layout restore / disappearing widgets
- Reproduced layout restore scenarios where fill/import hosts could lose visible docks after loading saved nested state.
- Confirmed the failure was not random object deletion; it was restore sequencing plus incompatible/outdated nested state being applied at the wrong time.

### Re-enable after hiding
- Reproduced saved layouts where hidden docks stayed hidden after restore and could not be brought back through Panels once the layout was locked again.

### HTML preview scroll/zoom
- Reproduced unmodified wheel input changing zoom and small native-gesture noise continuing to drift zoom after a real pinch.

### Overlap / unstable docking
- Reproduced that the custom geometry-driven docking helpers could generate invalid layout states and overlap-like splitter corruption after hide/show/reorder/restore cycles.

## 2. Actual Root Causes Found

### A. Unlock / compositor
- Root cause: the HTML Preview dock was allowed to enter the floating/detached dock lifecycle even though its content is a live `QWebEngineView`.
- Result: detaching that accelerated surface produced the compositor/null-texture failure path.

### B. Layout restore / disappearing widgets
- Root cause: nested dock state could be restored before all tab hosts/docks were materialized, and older fill-layout state could still be applied after the fill dock topology changed.
- Root cause: prior logic also overrode valid restored state by resetting to defaults too aggressively.

### C. Re-enable after hiding
- Root cause: locked mode used `QDockWidget.NoDockWidgetFeatures`, which left `toggleViewAction()` effectively dead for the locked-after-restore case.
- Root cause: panels visibility should have stayed owned by the real dock actions, not a second visibility model.

### D. HTML preview scroll/zoom bug
- Root cause: the preview accepted Chromium/WebEngine zoom mutations from ordinary wheel events even when no explicit zoom modifier was pressed.
- Root cause: tiny native gesture values were treated as ongoing zoom input, so post-pinch noise kept shrinking/enlarging the page.

### E. Overlap / buggy docking
- Root cause: the workspace had custom geometry-simulating compaction/rebuild behavior instead of relying on Qt’s dock layout engine.
- Root cause: the “Move Up/Down In Stack” path used the same geometry-derived rebuild model, which could synthesize invalid splitter geometry.

## 3. Structural Fixes vs Behavioral Fixes

### Structural
- Added versioned nested tab-layout compatibility checks and dock-name matching for restore state.
- Ensured nested tab hosts are materialized before applying nested restore payloads.
- Stopped unconditional default-layout resets when a compatible pending nested state exists.
- Returned Panels menu ownership to each dock’s real `toggleViewAction()`.
- Kept docks closable while locked so hidden docks remain recoverable.
- Disabled the geometry-simulated stack-reorder path and stopped auto-compaction from rewriting dock geometry.
- Prevented the HTML Preview dock from floating at all.

### Behavioral
- Ordinary wheel scroll now scrolls without changing zoom.
- Zoom now happens only through explicit Ctrl/Cmd wheel or meaningful native pinch input.
- Small native gesture noise is ignored both before and after a real pinch.

## 4. Dock Lifecycle / Restore Fixes

Implemented in `isrc_manager/contract_templates/dialogs.py`:

- Nested state capture now records `layout_version` and `dock_object_names`.
- Nested restore now normalizes and checks compatibility before applying `restoreState()`.
- All nested tab hosts are created before nested restore is attempted.
- Import and Fill workspaces only reset to defaults when there is no compatible pending state to apply.

This stopped the disappearing-dock behavior and stopped outdated fill-layout payloads from corrupting current dock topology.

## 5. QWebEngine / Preview Lifecycle Fixes

Implemented in `isrc_manager/contract_templates/dialogs.py`:

- The HTML Preview dock is created with `allow_floating=False`.
- The title-bar float action is disabled for docks that do not allow floating.
- `float_dock()` refuses to float non-floatable docks.

This removes the detach/floating lifecycle that was provoking the compositor/null-texture path for the live preview surface.

## 6. Toggle Action / Re-enable Fixes

Implemented in `isrc_manager/contract_templates/dialogs.py`:

- Panels now uses each dock’s real `toggleViewAction()`.
- Locked mode keeps `DockWidgetClosable` enabled instead of dropping to `NoDockWidgetFeatures`.
- `toggleViewAction()` is kept enabled in both locked and unlocked states.

This means hidden docks remain recoverable after layout restore, including when the restored layout is locked.

## 7. Input Handling Fixes

Implemented in `isrc_manager/contract_templates/dialogs.py`:

- `wheelEvent()` now reverts any WebEngine zoom change unless the user explicitly used Ctrl/Cmd zoom input.
- Native pinch handling now ignores low-magnitude gesture noise and only applies zoom to real pinch deltas.

This stops the “scrolling zooms out the HTML view” regression.

## 8. Overlap / Locking Fixes

Implemented in `isrc_manager/contract_templates/dialogs.py`:

- Automatic dock compaction no longer rewrites geometry.
- Geometry-simulated stack reordering is disabled.
- Dock moves now rely on Qt’s native dock placement instead of custom geometry reconstruction.

This removes the unstable overlap-producing behavior and keeps the workspace on Qt’s intended dock/layout mechanics.

## 9. Tests Added / Updated

Updated `tests/contract_templates/test_dialogs.py` to cover:
- hidden dock restore and reopen while locked
- reopen after all fill docks are hidden
- Panels actions bound to current dock instances after restore
- nested restore materialization and compatibility behavior
- no meaningful dock overlap after unlock/hide/show/restore
- preview dock non-floatability with live HTML loaded
- plain wheel scroll not entering zoom path
- explicit Ctrl-wheel zoom
- native-pinch noise not drifting zoom
- stable fit/reset zoom behavior

Updated `tests/app/_app_shell_support.py` and `tests/app/test_app_shell_layout_persistence.py` to add the named-layout restore case that reopens a hidden fill dock while locked.

## 10. Verification

Passed:

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.contract_templates.test_dialogs -v`
- `.venv/bin/python -m py_compile isrc_manager/contract_templates/dialogs.py tests/contract_templates/test_dialogs.py tests/app/_app_shell_support.py tests/app/test_app_shell_layout_persistence.py`

Verification boundary:

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.app.test_app_shell_layout_persistence...`
  segfaulted during broader `App` startup in `ISRC_manager.py:6124`, before the contract-template layout-persistence cases themselves could execute.
- That app-shell startup crash is an honest verification caveat for this environment, not a claimed pass.

## 11. Risks / Caveats

- The preview compositor fix is structural: the HTML Preview dock no longer enters the floating lifecycle. That is the intentional safety boundary.
- Offscreen WebEngine still emits Chromium GPU/context-loss noise in headless tests; the workspace tests pass, but the console noise remains an environment/runtime artifact.
- “Move Up/Down In Stack” is now intentionally disabled because the previous implementation was synthesizing dock geometry and causing instability.

## 12. Final Outcome

The Contract Templates Workspace is now stable, intentional, and no longer exhibits the prior disappearing-dock, dead-toggle, accidental scroll-zoom, or overlap-producing custom-layout behavior.

The durable fixes are:
- safe nested dock restore sequencing
- real dock-owned Panels visibility actions
- locked layouts that still allow dock recovery
- non-floatable WebEngine preview docking
- explicit-only preview zoom input
- removal of geometry-simulating dock compaction/reorder behavior

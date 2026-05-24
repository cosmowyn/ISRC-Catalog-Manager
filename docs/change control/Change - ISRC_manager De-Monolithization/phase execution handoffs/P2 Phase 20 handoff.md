# P2 Phase 20 Handoff - Lean App Move

Completion timestamp: 2026-05-25 00:20 CEST

## Scope Executed
- Executed Plan 2 Phase 20 only.
- Moved the current lean `App` module body from `ISRC_manager.py` to `isrc_manager/main_window.py`.
- Reduced `ISRC_manager.py` to a startup/compatibility facade that imports the moved main-window module, exposes `App`, and keeps `main()` as the project entrypoint.
- Preserved root patch seams and root import compatibility for Phase 21 cleanup rather than removing them early.

## Files Inspected
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-20 - Lean App Move.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `tests/test_helpers.py`
- `tests/test_app_bootstrap.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `pyproject.toml`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Files Added
- `isrc_manager/main_window.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 20 handoff.md`

## Compatibility Inventory Status
- Unchanged.
- No compatibility aliases were added, changed, migrated, or removed.
- Active alias count remains 42.
- Existing root re-export behavior was preserved through the temporary Phase 20 facade and remains assigned to Phase 21 cleanup.

## Root Alias and Wrapper Status
- Root alias additions/removals: none recorded in the inventory.
- Deprecated wrapper additions/removals: none recorded in the inventory.
- Temporary migration glue introduced: `ISRC_manager.py` now copies non-dunder attributes from `isrc_manager.main_window` into the root module to preserve pre-existing root patch/import seams until Phase 21.
- The root `main()` implementation intentionally remains in `ISRC_manager.py` so existing tests and launchers can patch root `run_desktop_application`, `run_packaged_smoke_test`, `init_settings`, and startup helpers during Phase 20.

## Architecture Boundary Observations
- `isrc_manager/main_window.py` owns the moved `App` class and existing shell orchestration after Phase 20.
- `ISRC_manager.py` no longer locally defines `App`; it imports the moved class and exposes bootstrap glue.
- `main_window_shell.py` was not split because Phase 17 already left it as the current shell-composition module and Phase 20 did not need a further split.
- `isrc_manager/main_window.py` includes a temporary file-level Ruff suppression for unused/import-order findings caused by compatibility re-exports that still exist before Phase 21.
- Phase 20 did not perform final compatibility cleanup or test root-import migration.

## Package Parity and Import-Cycle Status
- Package parity unchanged and valid: 27 pyproject packages match 27 filesystem packages.
- No package visibility change was required because `isrc_manager.main_window` is inside the existing top-level `isrc_manager` package.
- Static import-cycle count remains at the baseline of 3.
- No `isrc_manager` package module imports `ISRC_manager`.

## Module-Size / Mini-Monolith Risk
- `ISRC_manager.py` is now 56 LOC.
- `isrc_manager/main_window.py` is 9,781 LOC and `App` is 8,990 LOC.
- The moved main-window module is intentionally above the mandatory split threshold because Phase 20 moves the lean shell as-is; Phase 21 is still required to remove final root aliases, temporary re-exports, and dead wrappers.

## Architecture Metrics Impact
- Metrics changed and were recorded in `architecture_metrics.md`.
- Root import count remains 8 Python test imports.
- Package parity remains valid.
- Import-cycle count remains at 3.

## Validation
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/main_window.py`
- `.venv/bin/python -m ruff check ISRC_manager.py isrc_manager/main_window.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import ISRC_manager and isrc_manager.main_window ... PY`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_helpers.py tests/test_app_bootstrap.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -q`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python ISRC_manager.py --packaged-smoke-test`
- `git diff --check`

## Results
- Compile passed.
- Ruff passed for the root facade and moved main-window module.
- Import smoke passed.
- Helper and bootstrap tests passed: 20 passed.
- Catalog workspace route startup test passed: 1 passed, 34 deselected.
- App-shell workspace dock tests passed: 40 passed.
- Packaged smoke entrypoint passed.
- Whitespace check passed.

## Scope Compliance
- No final compatibility cleanup was performed.
- No tests were migrated away from root `ISRC_manager` imports in this phase.
- No build metadata or CI configuration was changed.
- No unrelated behavior work was performed.

## Remaining Risks Before Phase 21
- `ISRC_manager.py` still contains a temporary root re-export facade and must be reduced to bootstrap imports, `main()`, and startup glue only in Phase 21.
- `isrc_manager/main_window.py` still carries the remaining lean `App` and is above the mandatory split threshold.
- Eight tests still import the root module and must migrate before zero-debt cleanup can pass.
- Compatibility inventory still has 42 active entries that must be removed or marked historical removed during Phase 21.

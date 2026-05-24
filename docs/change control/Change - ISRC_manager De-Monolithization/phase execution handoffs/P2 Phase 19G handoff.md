# P2 Phase 19G Handoff - Update Workflow Controller Finalization

Completion timestamp: 2026-05-25 00:03 CEST

## Scope Executed
- Executed Plan 2 Phase 19G only.
- Moved update backup/cache handoff cleanup, startup/manual update checks, update-available prompts, release notes, update install preparation, and updater helper launch orchestration out of `App`.
- Added `isrc_manager.update_controller`.
- Changed the matching `App` methods into thin delegation shims.

## Files Inspected
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`
- `ISRC_manager.py`
- `isrc_manager/update_checker.py`
- `isrc_manager/update_handoff.py`
- `isrc_manager/update_installer.py`
- `tests/test_update_checker.py`
- `tests/test_update_ui_integration.py`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Files Added
- `isrc_manager/update_controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19G handoff.md`

## Compatibility Inventory Status
- Unchanged.
- No compatibility aliases were added, changed, migrated, or removed.
- Active alias count remains 42.
- Every active alias remains planned for removal in Plan 2 Phase 21.

## Architecture Boundary Observations
- `isrc_manager.update_controller` imports no root `ISRC_manager` module.
- Root-patched update tests are preserved through lazy root attribute lookups for update handoff helpers, installer helpers, release-notes fetches, message boxes, release-notes dialog, and the root `sys` object.
- The new controller is 596 LOC and below the warning threshold.
- Phase 19G did not create permanent migration glue; the remaining `App` methods are delegation shims for the ongoing Plan 2 decomposition.

## Package Parity and Import-Cycle Status
- Package parity unchanged and valid: 27 pyproject packages match 27 filesystem packages.
- No package visibility change was required because the new module is inside the existing `isrc_manager` package.
- Static import-cycle count remains at the baseline of 3.
- No `isrc_manager` package module imports `ISRC_manager`.

## Validation
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/update_controller.py`
- `.venv/bin/python -m ruff check isrc_manager/update_controller.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import isrc_manager.update_controller ... PY`
- `rg -n "from ISRC_manager|import ISRC_manager|ISRC_manager\\." isrc_manager/update_controller.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_update_checker.py tests/test_update_ui_integration.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import ISRC_manager ... PY`

## Results
- Compile passed.
- Ruff passed.
- Import smoke passed.
- Root-import scan returned no matches.
- Update checker/UI integration tests passed: 28 passed.
- Root `ISRC_manager` import smoke passed.

## Remaining Risks Before Phase 19H
- Promo code import and ledger update orchestration still lives on `App` and should be moved next.
- Existing root-patched app-shell tests still require root import migration before Phase 21 can remove aliases and wrappers.

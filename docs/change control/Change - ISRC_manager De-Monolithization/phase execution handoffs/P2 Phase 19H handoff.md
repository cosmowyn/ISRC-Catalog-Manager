# P2 Phase 19H Handoff - Promo Code Workflow Controllers

Completion timestamp: 2026-05-25 00:05 CEST

## Scope Executed
- Executed Plan 2 Phase 19H only.
- Moved Promo Code Ledger panel factory, dock creation, open route, Bandcamp CSV import, ledger update, and panel refresh orchestration out of `App`.
- Added `isrc_manager.promo_codes.controller`.
- Changed the matching `App` methods into thin delegation shims.

## Files Inspected
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`
- `ISRC_manager.py`
- `isrc_manager/promo_codes/__init__.py`
- `isrc_manager/promo_codes/dialogs.py`
- `isrc_manager/promo_codes/service.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/_app_shell_support.py`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Files Added
- `isrc_manager/promo_codes/controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19H handoff.md`

## Compatibility Inventory Status
- Unchanged.
- No compatibility aliases were added, changed, migrated, or removed.
- Active alias count remains 42.
- Every active alias remains planned for removal in Plan 2 Phase 21.

## Architecture Boundary Observations
- `isrc_manager.promo_codes.controller` imports no root `ISRC_manager` module.
- Root-patched seams are preserved through lazy root attribute lookups for message boxes, the ledger panel class, and snapshot-history helper calls.
- The new controller is 242 LOC and below the warning threshold.
- Phase 19H did not create permanent migration glue; the remaining `App` methods are delegation shims for the ongoing Plan 2 decomposition.

## Package Parity and Import-Cycle Status
- Package parity unchanged and valid: 27 pyproject packages match 27 filesystem packages.
- No package visibility change was required because the new module is inside the existing `isrc_manager.promo_codes` package.
- Static import-cycle count remains at the baseline of 3.
- No `isrc_manager` package module imports `ISRC_manager`.

## Validation
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/promo_codes/controller.py`
- `.venv/bin/python -m ruff check isrc_manager/promo_codes/controller.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import isrc_manager.promo_codes.controller ... PY`
- `rg -n "from ISRC_manager|import ISRC_manager|ISRC_manager\\." isrc_manager/promo_codes/controller.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import ISRC_manager, PromoCodeLedgerPanel, PromoCodeService, controller ... PY`

## Results
- Compile passed.
- Ruff passed.
- Import smoke passed.
- Root-import scan returned no matches.
- Catalog workspace route test passed: 1 passed, 34 deselected.
- Promo code service/panel/controller import smoke passed.

## Remaining Risks Before Phase 19I
- Contract templates, contracts, rights, assets, and parties workflow orchestration still live on `App` and should be moved next.
- The repository does not currently include a dedicated promo-code service/dialog test file; validation used the available app-shell route coverage and import smoke.
- Existing root-patched app-shell tests still require root import migration before Phase 21 can remove aliases and wrappers.

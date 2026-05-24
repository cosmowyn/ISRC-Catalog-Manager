# P2 Phase 19I Handoff - Contract Templates, Contracts, Rights, Assets, and Parties Controllers

Completion timestamp: 2026-05-25 00:14 CEST

## Scope Executed
- Executed Plan 2 Phase 19I only.
- Moved Party Manager panel/dock/opening, owner-party binding/bootstrap, party exchange import/export, artist-party choice helpers, party authority refresh handling, party manager selection, and owner-registration redirection orchestration out of `App`.
- Moved Contract Manager panel/dock/opening and contract create/update/delete history orchestration out of `App`.
- Moved Contract Template Workspace panel/dock/opening orchestration out of `App`.
- Moved Rights Matrix and Asset Registry panel/dock/opening orchestration out of `App`.
- Changed the matching `App` methods into thin delegation shims.

## Files Inspected
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`
- `ISRC_manager.py`
- `isrc_manager/parties/__init__.py`
- `isrc_manager/parties/dialogs.py`
- `isrc_manager/parties/exchange_service.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/contracts/__init__.py`
- `isrc_manager/contracts/dialogs.py`
- `isrc_manager/contracts/service.py`
- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/rights/dialogs.py`
- `isrc_manager/rights/service.py`
- `isrc_manager/assets/dialogs.py`
- `isrc_manager/assets/service.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/_app_shell_support.py`
- `tests/test_party_exchange_service.py`
- `tests/test_party_import_dialog.py`
- `tests/test_work_and_party_services.py`
- `tests/test_repertoire_dialogs.py`
- `tests/catalog/test_contract_service.py`
- `tests/test_contract_template_service.py`
- `tests/contract_templates/test_revision_service.py`
- `tests/contract_templates/test_scanner.py`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Files Added
- `isrc_manager/parties/controller.py`
- `isrc_manager/contracts/controller.py`
- `isrc_manager/contract_templates/controller.py`
- `isrc_manager/rights/controller.py`
- `isrc_manager/assets/controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19I handoff.md`

## Compatibility Inventory Status
- Unchanged.
- No compatibility aliases were added, changed, migrated, or removed.
- Active alias count remains 42.
- Every active alias remains planned for removal in Plan 2 Phase 21.

## Architecture Boundary Observations
- New workflow orchestration is split by existing domain package instead of being placed in a broad cross-domain controller.
- `isrc_manager.parties.controller`, `isrc_manager.contracts.controller`, `isrc_manager.contract_templates.controller`, `isrc_manager.rights.controller`, and `isrc_manager.assets.controller` import no root `ISRC_manager` module.
- Root-patched app-shell seams are preserved through lazy root attribute lookups for message boxes, file dialogs, party dialogs, panel classes, and history helper calls.
- New module sizes are: parties controller 1,141 LOC, contracts controller 125 LOC, contract templates controller 63 LOC, rights controller 56 LOC, and assets controller 56 LOC.
- The party controller is close to the 1,200 LOC warning threshold and should be watched during Phase 20/21 cleanup, but it remains below the warning threshold and did not combine unrelated non-party workflows.
- Phase 19I did not create permanent migration glue; remaining `App` methods are delegation shims for the ongoing Plan 2 decomposition.

## Package Parity and Import-Cycle Status
- Package parity unchanged and valid: 27 pyproject packages match 27 filesystem packages.
- No package visibility change was required because all new modules are inside existing packages.
- Static import-cycle count remains at the baseline of 3.
- No `isrc_manager` package module imports `ISRC_manager`.

## Validation
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/parties/controller.py isrc_manager/contracts/controller.py isrc_manager/contract_templates/controller.py isrc_manager/rights/controller.py isrc_manager/assets/controller.py`
- `.venv/bin/python -m ruff check isrc_manager/parties/controller.py isrc_manager/contracts/controller.py isrc_manager/contract_templates/controller.py isrc_manager/rights/controller.py isrc_manager/assets/controller.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import controllers and ISRC_manager ... PY`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_work_and_party_services.py tests/test_repertoire_dialogs.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/catalog/test_contract_service.py tests/test_contract_template_service.py tests/contract_templates/test_revision_service.py tests/contract_templates/test_scanner.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'catalog_workspace_menu_groups_intent_actions_and_preserves_workspace_routes'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_party_exchange_service.py tests/test_party_import_dialog.py`
- `git diff --check`

## Results
- Compile passed.
- Ruff passed for the new controller modules.
- Import smoke passed.
- Party/work service and repertoire dialog tests passed: 41 passed.
- Contract service/template service/revision/scanner tests passed: 41 passed.
- App-shell workspace dock tests passed: 40 passed.
- Catalog workspace route startup test passed: 1 passed, 34 deselected.
- Party exchange service and party import dialog tests passed: 12 passed.
- Whitespace check passed.

## Remaining Risks Before Phase 20
- `ISRC_manager.py` still contains `App` and root compatibility re-exports; Phase 20 must reduce the entry facade without beginning the Phase 21 alias cleanup early.
- The party controller is close to the module-size warning threshold and should not absorb additional unrelated responsibilities.
- Existing root-patched app-shell tests still require root import migration before Phase 21 can remove aliases and wrappers.

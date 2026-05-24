# Plan 2 Phase 15 Handoff - Diagnostics Report and Controller

Completion timestamp: 2026-05-24 22:24:51 CEST

## Scope Confirmation

Executed only Plan 2 Phase 15 from the Phase 2 prompt set.

The phase was limited to diagnostics report assembly, diagnostics repair orchestration, and application storage audit/cleanup orchestration. No theme/settings/history/app-sound extraction, layout/action-ribbon extraction, catalog workflow extraction, feature workflow extraction, root compatibility cleanup, or Phase 16+ work was performed. `DiagnosticsDialog` and `ApplicationStorageAdminDialog` remain in `isrc_manager.app_dialogs`.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-15 - Diagnostics Report and Controller.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `isrc_manager/app_dialogs.py`
- `isrc_manager/storage_admin.py`
- `tests/test_app_dialogs.py`
- `tests/test_storage_admin_service.py`
- `tests/test_theme_builder.py`
- `tests/app/test_app_shell_storage_root_transitions.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/app/_app_shell_support.py`

## Files Added

- `isrc_manager/diagnostics/__init__.py`
- `isrc_manager/diagnostics/report.py`
- `isrc_manager/diagnostics/controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 15 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `pyproject.toml`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Added the `isrc_manager.diagnostics` package and registered it in `pyproject.toml`.
- Moved diagnostics report data assembly into `isrc_manager.diagnostics.report`.
- Moved application storage audit payload assembly into `isrc_manager.diagnostics.report`.
- Moved diagnostics repair preview/execution, background diagnostics report loading, and application storage async audit/cleanup orchestration into `isrc_manager.diagnostics.controller`.
- Left thin App delegation methods in place so existing dialogs, runtime call sites, and tests retain stable entry points during Plan 2.
- Kept `DiagnosticsDialog` and `ApplicationStorageAdminDialog` in `isrc_manager.app_dialogs`.

## Compatibility Inventory Status

Unchanged.

No compatibility aliases were added, removed, migrated, or changed. Active alias count remains 42.

## Root Alias / Wrapper Status

- Root alias additions: none.
- Root alias removals: none.
- Deprecated wrapper additions/removals: none.
- App delegation shims: added for moved diagnostics/report/storage methods only.
- Permanent migration glue: none; the delegation shims are transitional Plan 2 extraction seams.
- New compatibility alias requirements: not applicable; no new alias was introduced.

## Architecture Boundary Observations

- `isrc_manager.diagnostics.report` and `isrc_manager.diagnostics.controller` do not import root `ISRC_manager` or `App`.
- The diagnostics modules accept the live App host as an orchestration object to preserve stable App entry points and existing dialog contracts.
- Dialog/UI ownership remains in `isrc_manager.app_dialogs` as required by the phase prompt.
- Application storage service behavior remains in `isrc_manager.storage_admin`; Phase 15 only moved App orchestration and payload assembly around that service.

## Package / Import-Cycle Observations

- Package parity impact: changed and valid; `isrc_manager.diagnostics` was added to `pyproject.toml`, and 26 pyproject package entries match 26 filesystem packages.
- Import-cycle risk: controlled; static import-cycle component count remains 3, matching the Plan 2 entry baseline.
- Existing static cycle components remain:
  - `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
  - `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
  - `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`

## Module-Size / Mini-Monolith Risk

- `isrc_manager/diagnostics/report.py`: 1,195 LOC.
- `isrc_manager/diagnostics/controller.py`: 704 LOC.
- Both new diagnostics modules are below the 1,200 LOC warning threshold.
- No new package module crossed the warning or mandatory split threshold.
- `ISRC_manager.py` dropped from 26,173 LOC to 24,572 LOC.
- `App` dropped from 25,417 LOC to 23,814 LOC.

## Architecture Metrics Impact

Changed.

Recorded Phase 15 metrics in `architecture_metrics.md`:

- `ISRC_manager.py` LOC: 24,572
- `App` LOC: 23,814
- active compatibility aliases: 42
- root test import count: 8
- package module warning threshold count: 34
- package module mandatory split threshold count: 11
- import-cycle count: 3
- package parity: changed and valid at 26/26

## QA Checks

Passed:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/diagnostics`
- `.venv/bin/python -m ruff check isrc_manager/diagnostics`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import isrc_manager.diagnostics.report/controller ... PY`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_app_dialogs.py -k 'diagnostics or application_storage'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_storage_root_transitions.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -k 'diagnostics_catalog_cleanup or catalog_cleanup_legacy_route'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_storage_admin_service.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_theme_builder.py -k 'application_storage'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_app_bootstrap.py -k 'packaged or import or startup'`
- `git diff --check`

Focused pytest results:

- 7 passed, 8 deselected
- 3 passed
- 3 passed, 37 deselected
- 7 passed
- 1 passed, 26 deselected
- 2 passed, 9 deselected

## QC Checks

- Confirmed Engineering Plan 2 and the mandatory architecture enforcement plan before editing.
- Confirmed Phase 15 scope before editing.
- Confirmed dialogs remained in `isrc_manager.app_dialogs`.
- Confirmed package visibility was updated for the new `isrc_manager.diagnostics` package.
- Confirmed no Phase 16 settings/theme/history/app-sound controller work was performed.
- Confirmed no compatibility inventory entry was required.
- Confirmed no permanent migration glue was introduced.

## Intentionally Not Implemented

- No diagnostics UI/dialog extraction.
- No theme, settings, history retention, or app sound controller extraction.
- No layout, workspace shell, or action-ribbon controller extraction.
- No catalog workflow controller extraction.
- No feature workflow controller extraction.
- No root compatibility alias cleanup.
- No test migration away from root imports.

## Risks / Follow-Up Notes

- The diagnostics modules still use the live App object as a host seam. Later phases should narrow this as more controllers own their dependencies directly.
- `diagnostics/report.py` is close to the warning threshold at 1,195 LOC. Avoid expanding it into a broad diagnostics platform; future additions should prefer smaller collaborators when responsibility grows.
- Root compatibility aliases remain at 42 and are still assigned to Plan 2 Phase 21 cleanup.
- The pre-existing static import-cycle baseline remains at 3 components and should not increase in later phases.

## Repo-Specific Conventions

- `app_dialogs.py` calls App diagnostics methods by name, so Phase 15 preserved those App methods as thin delegation shims.
- Application storage cleanup semantics belong to `ApplicationStorageAdminService`; UI/controller layers should not duplicate deletion rules.
- New packages must be added to the explicit `pyproject.toml` package list.

# Plan 2 Phase 17 Handoff - Layout, Workspace Shell, and Action Ribbon Controllers

Completion timestamp: 2026-05-24 22:49:43 CEST
Status: Completed

## Source Documents Read

- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-17 - Layout, Workspace Shell, and Action Ribbon Controllers.md`

## Files Inspected

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `tests/test_main_window_shell_conversion.py`
- `tests/test_main_window_shell_settings_transfer.py`
- `tests/app/test_app_shell_layout_persistence.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/app/_app_shell_support.py`

## Files Added

- `isrc_manager/main_window_layout.py`
- `isrc_manager/action_ribbon.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 17 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Moved named main-window layout persistence, layout serialization, layout restore preparation/application, dock-state persistence, workspace panel layout snapshots, first-show workspace restore, and saved layout menu/ribbon UI hooks to `isrc_manager.main_window_layout`.
- Moved action ribbon registry setup, action id normalization, ribbon persistence, saved-layout ribbon snapshot handling, ribbon toolbar rebuild, profile/action ribbon visibility, action ribbon context menu, and action ribbon customizer orchestration to `isrc_manager.action_ribbon`.
- Moved the display toggle handlers for column width, row height, Add Track panel, Catalog Table panel, Profiles Ribbon, and Action Ribbon into the Phase 17 controller modules.
- Kept `isrc_manager.main_window_shell` as the shell-composition module that builds actions, menus, toolbars, and docks.
- Preserved `App` method names as thin delegation shims for current runtime callers and tests.

## Why It Changed

Phase 17 required layout, workspace shell state, and action ribbon responsibilities to move out of the oversized `App` body while keeping the existing shell composition stable. The split separates persisted layout/ribbon orchestration from menu/toolbar/dock construction without starting catalog workflow extraction.

## Scope Control

- Scope remained limited to Plan 2 Phase 17.
- No catalog workflow extraction was performed.
- No feature-family workflow extraction was performed.
- No final `App` move was performed.
- No Phase 18+ implementation was started.
- `main_window_shell.py` was not split further because its current composition role remains cohesive after moving layout persistence and action ribbon orchestration.
- Root-module dialog patch compatibility was preserved for existing tests by resolving patched root-module dialog helpers/classes at runtime from the extracted modules.

## Intentionally Not Implemented

- Catalog dataset refresh, search/filter/count/duration, context menus, media/blob routing, and ISRC registry orchestration; this belongs to Phase 18.
- Feature workflow controllers; these belong to Phase 19 subphases.
- Final root compatibility cleanup; this belongs to Phase 21.
- CI architecture enforcement scripts; this remains future tooling work under the governance plan.

## QA Checks

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/main_window_layout.py isrc_manager/action_ribbon.py`
- `.venv/bin/python -m ruff check isrc_manager/main_window_layout.py isrc_manager/action_ribbon.py`
- Import smoke for `isrc_manager.main_window_layout` and `isrc_manager.action_ribbon`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window_shell_conversion.py tests/test_main_window_shell_settings_transfer.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_layout_persistence.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'layout or ribbon or menus or startup_first_launch_prompt_can_open_settings_and_clears_pending_flag'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -k 'workspace_layout or dock or ribbon or restore'`
- `git diff --check`

Results:

- Compile/import sanity passed.
- Ruff passed for the new Phase 17 modules.
- Main-window shell conversion/settings transfer tests passed: 3 passed.
- Layout persistence tests passed: 16 passed.
- Startup-core layout/ribbon/menu focused tests passed: 7 passed, 28 deselected.
- Workspace dock focused tests passed: 40 passed.
- Whitespace check passed.

## QC Checks

- Verified the engineering plan and Phase 17 prompt were read before finalizing the phase.
- Verified source changes are limited to `ISRC_manager.py` delegation shims and the allowed Phase 17 modules.
- Verified no adjacent Phase 18+ catalog or feature workflow logic was implemented.
- Verified `main_window_shell.py` remains the shell-composition module.
- Verified extracted modules do not import `App`.
- Verified no package metadata update was required because no new package was introduced.
- Verified architecture metrics were recorded after validation.

## Compatibility Inventory

- Compatibility inventory change status: unchanged.
- Root alias additions: none.
- Root alias removals: none.
- Deprecated wrapper additions: none.
- Deprecated wrapper removals: none.
- Active compatibility alias count remains 42.
- No new compatibility alias was added; therefore no new target path, deprecation policy, removal phase, or inventory entry was required.

## Architecture Boundary Observations

- `main_window_layout.py` owns layout persistence/restore and dock visibility orchestration only.
- `action_ribbon.py` owns action ribbon registry/configuration/customization only.
- `main_window_shell.py` continues to own shell composition and action/menu/dock construction.
- Catalog workflow behavior remains in place for Phase 18; Phase 17 only calls existing App hooks where layout/ribbon operations already depended on them.
- The extracted modules preserve root-module dialog patch compatibility without creating public root aliases.

## Package Parity, Import Cycles, and Module Size

- Package parity impact: unchanged and valid; 26 pyproject packages match 26 filesystem packages.
- Import-cycle risk: no new static import-cycle components detected. Count remains 3:
  - `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
  - `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
  - `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`
- Module-size / mini-monolith risk:
  - `isrc_manager/main_window_layout.py`: 1,579 LOC, above the 1,200 LOC warning threshold but below the 2,500 LOC mandatory split threshold.
  - `isrc_manager/action_ribbon.py`: 862 LOC, below the warning threshold.
  - `isrc_manager/main_window_shell.py`: 2,020 LOC, still above the warning threshold and below the mandatory split threshold.

## Architecture Metrics Impact

- `ISRC_manager.py` LOC: 21,317
- `App` LOC: 20,555
- Compatibility alias count: 42 active entries
- Root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- Module LOC over warning threshold: 35 package modules at or above 1,200 LOC
- Module LOC over mandatory split threshold: 11 package modules at or above 2,500 LOC
- Import cycle count: 3
- Package parity status: valid
- Tests still using root imports:
  - `tests/app/_app_shell_support.py`
  - `tests/test_app_bootstrap.py`
  - `tests/test_history_budget_hooks.py`
  - `tests/test_migration_integration.py`
  - `tests/test_qss_autocomplete.py`
  - `tests/test_shortcut_ordering.py`
  - `tests/test_theme_builder.py`
  - `tests/test_update_ui_integration.py`

## Migration Glue and Aliases

- Dormant imports added: none.
- Permanent migration glue created: none.
- Temporary compatibility aliases added: none.
- Thin App delegation shims remain intentionally as transitional runtime entry points until later Plan 2 phases remove root/App dependency surfaces.

## Risks and Follow-Up Notes

- `main_window_layout.py` is above the warning threshold and should be watched during later shell cleanup.
- `main_window_shell.py` remains above the warning threshold; it was not further split during Phase 17 because the plan only permits splitting where it reduces coupling.
- Existing root-importing tests remain and must be addressed before the Phase 21 zero-debt cleanup gate.
- Phase 18 should build on the existing `CatalogTableController` and avoid pulling layout or action ribbon logic back into catalog workflow modules.

## Repo-Specific Conventions

- Use `.venv/bin/python` for local validation because the system interpreter does not provide the required PySide6 environment.
- Use `QT_QPA_PLATFORM=offscreen` for focused Qt tests.
- Existing app-shell tests patch dialog classes/helpers through the root `ISRC_manager` module; extracted UI orchestration that invokes dialogs must preserve that patchability until tests migrate away from root imports.

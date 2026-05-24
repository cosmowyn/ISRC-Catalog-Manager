# Plan 2 Phase 16 Handoff - Theme, Settings, History Retention, and App Sound Controllers

Completion timestamp: 2026-05-24 22:35:32 CEST
Status: Completed

## Source Documents Read

- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-16 - Theme, Settings, History Retention, and App Sound Controllers.md`

## Files Inspected

- `ISRC_manager.py`
- `isrc_manager/theme_builder.py`
- `isrc_manager/app_sounds.py`
- `isrc_manager/settings_transfer.py`
- `isrc_manager/settings_transfer_service.py`
- `tests/test_theme_builder.py`
- `tests/test_qss_autocomplete.py`
- `tests/test_history_cleanup_service.py`
- `tests/test_storage_admin_service.py`
- `tests/app/test_app_shell_startup_core.py`

## Files Added

- `isrc_manager/app_sound_controller.py`
- `isrc_manager/theme_controller.py`
- `isrc_manager/history_retention_controller.py`
- `isrc_manager/settings_controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 16 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Moved app sound and startup sound settings/playback orchestration to `isrc_manager.app_sound_controller`.
- Moved theme load, normalization, save, build, and apply orchestration to `isrc_manager.theme_controller`.
- Moved history retention, automatic snapshot scheduling, storage budget estimation, and storage budget enforcement orchestration to `isrc_manager.history_retention_controller`.
- Moved current settings, settings application, identity/window-title settings, application settings import/export, and single-setting application logic to `isrc_manager.settings_controller`.
- Replaced the matching `App` method bodies with thin delegation shims that preserve existing runtime entry points.
- Reused existing `theme_builder.py`, settings transfer services, and `app_sounds.py`; no replacement framework or duplicate media/sound infrastructure was introduced.

## Why It Changed

Phase 16 required the theme, settings, history retention, and app-sound responsibilities to leave the oversized `App` body while keeping behavior stable through delegation. The extraction reduces `ISRC_manager.py` and `App` size without widening into layout, action ribbon, catalog, or later feature-family workflow phases.

## Scope Control

- Scope remained limited to Plan 2 Phase 16.
- No layout/action ribbon extraction was performed.
- No catalog workflow extraction was performed.
- No feature-family workflow extraction was performed.
- No final `App` move was performed.
- No Phase 17+ implementation was started.
- Existing App entry points were preserved as delegation shims for current runtime callers and tests.

## Intentionally Not Implemented

- Layout and action-ribbon controller decomposition; this belongs to Phase 17.
- Track/editor/save workflow decomposition; this belongs to Phase 18.
- Catalog/media/quality/update/promo/contracts workflow decomposition; this belongs to Phase 19 subphases.
- Final root-entry facade cleanup; this belongs to Phase 21.
- CI architecture enforcement scripts; this remains future tooling work under the governance plan.

## QA Checks

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/app_sound_controller.py isrc_manager/theme_controller.py isrc_manager/history_retention_controller.py isrc_manager/settings_controller.py`
- `.venv/bin/python -m ruff check isrc_manager/app_sound_controller.py isrc_manager/theme_controller.py isrc_manager/history_retention_controller.py isrc_manager/settings_controller.py`
- Import smoke for `isrc_manager.app_sound_controller`, `isrc_manager.theme_controller`, `isrc_manager.history_retention_controller`, and `isrc_manager.settings_controller`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'sound or settings or bundled_themes or startup_first_launch_prompt_can_open_settings_and_clears_pending_flag'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_theme_builder.py tests/test_qss_autocomplete.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_history_cleanup_service.py tests/test_storage_admin_service.py`
- `git diff --check`

Results:

- Compile/import sanity passed.
- Ruff passed for the new Phase 16 controllers.
- Startup/settings/sound focused tests passed: 6 passed, 29 deselected.
- Theme builder and QSS autocomplete tests passed: 53 passed.
- History cleanup and storage admin tests passed: 19 passed.
- Whitespace check passed.

## QC Checks

- Verified the engineering plan and Phase 16 prompt were read before finalizing the phase.
- Verified source changes are limited to `ISRC_manager.py` delegation shims and the four allowed controller modules.
- Verified no adjacent phase implementation was introduced.
- Verified new controllers call existing services/helpers instead of replacing `theme_builder.py`, settings transfer services, or `app_sounds.py`.
- Verified no new packages were introduced, so package metadata did not require a Phase 16 update.
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

- Theme controller owns theme settings normalization/application orchestration only and delegates stylesheet/palette construction to `theme_builder.py`.
- Settings controller owns settings current/apply/import/export orchestration only and delegates bundle transfer work to the existing settings transfer services.
- History retention controller owns snapshot retention and storage-budget orchestration only; storage-admin and diagnostics workflows remain outside this phase.
- App sound controller owns application interaction and startup sound orchestration only and uses existing `app_sounds.py` path/effect helpers.
- No controller owns layout, ribbon, catalog, editor, media preview, diagnostics, or feature-family workflow responsibilities.

## Package Parity, Import Cycles, and Module Size

- Package parity impact: unchanged and valid; 26 pyproject packages match 26 filesystem packages.
- Import-cycle risk: no new static import-cycle components detected. Count remains 3:
  - `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
  - `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
  - `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`
- Module-size / mini-monolith risk:
  - `isrc_manager/app_sound_controller.py`: 206 LOC
  - `isrc_manager/theme_controller.py`: 400 LOC
  - `isrc_manager/history_retention_controller.py`: 445 LOC
  - `isrc_manager/settings_controller.py`: 858 LOC
  - All four modules are below the 1,200 LOC warning threshold.

## Architecture Metrics Impact

- `ISRC_manager.py` LOC: 23,274
- `App` LOC: 22,513
- Compatibility alias count: 42 active entries
- Root import count: 8 Python test imports; 0 `isrc_manager` package imports detected
- Module LOC over warning threshold: 34 package modules at or above 1,200 LOC
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

- `ISRC_manager.py` and `App` remain large after Phase 16; later Plan 2 phases must continue the decomposition.
- Existing root-importing tests remain and must be addressed before the Phase 21 zero-debt cleanup gate.
- Existing import-cycle baseline remains at 3 components; Phase 16 did not add cycles, but future controller work should avoid entangling new workflow modules with these components.
- Phase 17 should focus on layout and action registry/ribbon responsibilities only and should not pull the Phase 16 controllers back into `App`.

## Repo-Specific Conventions

- Use `.venv/bin/python` for local validation because the system interpreter does not provide the required PySide6 environment.
- Use `QT_QPA_PLATFORM=offscreen` for focused Qt tests.
- Keep root `ISRC_manager.py` validation scoped; full-file ruff debt is pre-existing and the repo excludes the root file from the normal ruff target.

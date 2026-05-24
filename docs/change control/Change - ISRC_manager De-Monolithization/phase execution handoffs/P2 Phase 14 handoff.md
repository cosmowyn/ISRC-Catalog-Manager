# Plan 2 Phase 14 Handoff - Profile, Storage, and Session Controller

Completion timestamp: 2026-05-24 22:17:40 CEST

## Scope Confirmation

Executed only Plan 2 Phase 14 from the Phase 2 prompt set.

The phase was limited to profile selection, profile CRUD, database preparation/open/close/session activation, storage-root transition, startup profile loading, and migration prompt orchestration. No diagnostics extraction, theme/settings/history/app-sound extraction, layout/action-ribbon extraction, catalog workflow extraction, feature workflow controller extraction, root compatibility cleanup, or Phase 15+ work was performed.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-14 - Profile, Storage, and Session Controller.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `isrc_manager/services/profiles.py`
- `isrc_manager/services/session.py`
- `tests/test_profile_workflow_service.py`
- `tests/test_paths.py`
- `tests/test_migration_integration.py`
- `tests/app/test_app_shell_profiles_and_selection.py`
- `tests/app/test_app_shell_startup_core.py`
- `tests/app/_app_shell_support.py`

## Files Added

- `isrc_manager/profile_session.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 14 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Added `isrc_manager.profile_session` for profile, storage-root, and database-session orchestration.
- Moved the storage layout application and startup migration prompt flow out of `App` into `profile_session`.
- Moved profile list reload, profile selection, profile creation, profile browsing, and profile deletion orchestration out of `App`.
- Moved database close, database preparation, blocking open preparation, database open, synchronous profile activation, background preparation, and background activation orchestration out of `App`.
- Left thin delegation methods on `App` so stable internal call sites and tests continue to use the existing entry points during the migration.
- Reused the existing `ProfileWorkflowService`, `DatabaseSessionService`, `DatabaseSchemaService`, storage migration service, startup progress helpers, and background task machinery.

## Compatibility Inventory Status

Unchanged.

No compatibility aliases were added, removed, migrated, or changed. Active alias count remains 42.

## Root Alias / Wrapper Status

- Root alias additions: none.
- Root alias removals: none.
- Deprecated wrapper additions/removals: none.
- App delegation shims: added for the moved profile/session methods only.
- Permanent migration glue: none; the delegation shims are transitional Plan 2 extraction seams.
- New compatibility alias requirements: not applicable; no new alias was introduced.

## Architecture Boundary Observations

- `isrc_manager.profile_session` does not import root `ISRC_manager` or `App`.
- The module accepts the live App host as an orchestration object because Phase 14 preserves stable entry points and existing startup/profile workflows.
- The module imports `QFileDialog`, `QInputDialog`, and `QMessageBox` because the phase explicitly includes migration prompt orchestration and profile CRUD prompts that were formerly owned by `App`.
- No diagnostics, settings/theme/history/app-sound, layout/action-ribbon, catalog, media, or feature workflow responsibility was moved into this module.

## Package / Import-Cycle Observations

- Package parity impact: unchanged; the new module lives inside the existing `isrc_manager` package.
- Import-cycle risk: controlled; static import-cycle component count remains 3, matching the Plan 2 entry baseline.
- Existing static cycle components remain:
  - `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
  - `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
  - `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`

## Module-Size / Mini-Monolith Risk

- `isrc_manager/profile_session.py`: 945 LOC.
- The new module is below the 1,200 LOC warning threshold.
- No new package module crossed the warning or mandatory split threshold.
- `ISRC_manager.py` dropped from 26,942 LOC to 26,173 LOC.
- `App` dropped from 26,187 LOC to 25,417 LOC.

## Architecture Metrics Impact

Changed.

Recorded Phase 14 metrics in `architecture_metrics.md`:

- `ISRC_manager.py` LOC: 26,173
- `App` LOC: 25,417
- active compatibility aliases: 42
- root test import count: 8
- package module warning threshold count: 34
- package module mandatory split threshold count: 11
- import-cycle count: 3
- package parity: unchanged and valid

## QA Checks

Passed:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/profile_session.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import isrc_manager.profile_session ... PY`
- `.venv/bin/python -m ruff check isrc_manager/profile_session.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_profile_workflow_service.py tests/test_paths.py -k 'profile or last_db or persisted'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_profiles_and_selection.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_migration_integration.py -k 'open_database or background'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'profile or storage or startup_first_launch_prompt_can_open_settings_and_clears_pending_flag'`
- `git diff --check`

Focused pytest results:

- 4 passed, 5 deselected
- 13 passed
- 2 passed
- 3 passed, 32 deselected

Additional note:

- A direct ruff invocation against `ISRC_manager.py` reports existing migration-era unused root compatibility imports. `ISRC_manager.py` is excluded by the repo ruff configuration, and Phase 14 did not change root alias inventory or compatibility import policy.

## QC Checks

- Confirmed Engineering Plan 2 and the mandatory architecture enforcement plan before editing.
- Confirmed Phase 14 scope before editing.
- Confirmed App wrappers delegate only to `isrc_manager.profile_session`.
- Confirmed no Phase 15 diagnostics/report/controller work was performed.
- Confirmed no Phase 16 settings/theme/history/app-sound controller work was performed.
- Confirmed no compatibility inventory entry was required.
- Confirmed no permanent migration glue was introduced.

## Intentionally Not Implemented

- No diagnostics report/controller extraction.
- No theme, settings, history retention, or app sound controller extraction.
- No layout, workspace shell, or action-ribbon controller extraction.
- No catalog workflow controller extraction.
- No feature workflow controller extraction.
- No root compatibility alias cleanup.
- No test migration away from root imports.

## Risks / Follow-Up Notes

- `profile_session` still uses the live App object as a host seam. Later phases should narrow this as controllers own more workflow surfaces.
- The module still orchestrates Qt prompts for profile and storage migration flows because those prompts are in Phase 14 scope; later UI boundary cleanup should avoid expanding this into a broader UI controller.
- Root compatibility aliases remain at 42 and are still assigned to Plan 2 Phase 21 cleanup.
- The pre-existing static import-cycle baseline remains at 3 components and should not increase in later phases.

## Repo-Specific Conventions

- App-shell tests use root `ISRC_manager` imports as the current migration-era integration entry point.
- Profile switching tests monkeypatch the existing App methods, so Phase 14 preserved those method names as thin delegation shims.
- New focused modules should live inside existing packages unless a phase explicitly changes package topology.

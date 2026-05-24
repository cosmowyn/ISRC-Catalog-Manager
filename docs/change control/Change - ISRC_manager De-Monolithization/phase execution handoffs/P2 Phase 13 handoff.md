# Plan 2 Phase 13 Handoff - Foreground Service Container

Completion timestamp: 2026-05-24 22:10:57 CEST

## Scope Confirmation

Executed only Plan 2 Phase 13 from the Phase 2 prompt set.

The phase was limited to foreground/UI-thread service graph wiring. No profile/session extraction, diagnostics extraction, theme/settings/history/app-sound extraction, unrelated controller decomposition, worker-thread service merge, Phase 14+ work, or Plan 2 compatibility cleanup was performed.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-13 - Foreground Service Container.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `isrc_manager/tasks/app_services.py`
- `tests/test_app_bootstrap.py`
- `tests/test_background_app_services.py`
- `tests/test_migration_integration.py`
- `tests/app/test_app_shell_startup_core.py`

## Files Added

- `isrc_manager/app_services.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 13 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Added `isrc_manager.app_services` for foreground/UI-thread service wiring.
- Moved `App._init_services` service construction into `initialize_foreground_services(app)`.
- Moved the foreground exchange/search/tag/quality/GS1 service construction that was previously coupled to `_refresh_audio_conversion_action_states` into `configure_foreground_exchange_services(app)`.
- Left `_refresh_audio_conversion_action_states` on `App` as UI action-state logic, delegating service construction to the foreground service module.
- Left `isrc_manager.tasks.app_services.BackgroundAppServiceFactory` untouched and worker-thread focused.

## Compatibility Inventory Status

Unchanged.

No compatibility aliases were added, removed, migrated, or changed. Active alias count remains 42.

## Root Alias / Wrapper Status

- Root alias additions: none.
- Root alias removals: none.
- Deprecated wrapper additions/removals: none.
- Permanent migration glue: none.
- New compatibility alias requirements: not applicable; no new alias was introduced.

## Architecture Boundary Observations

- `isrc_manager.app_services` is a foreground/UI-thread wiring module and does not import root `ISRC_manager` or `App`.
- `isrc_manager.tasks.app_services` remains the worker-thread service bundle factory and was not merged with foreground wiring.
- The foreground module uses the live App host only as an object passed into functions; it does not own App or profile/session behavior.
- Phase 14 profile/session extraction remains untouched.

## Package / Import-Cycle Observations

- Package parity impact: unchanged; the new module lives inside the existing `isrc_manager` package.
- Import-cycle risk: controlled; static import-cycle component count remains 3, matching the entry baseline.
- The new module imports lower-level services/controllers and has no dependency on root.

## Module-Size / Mini-Monolith Risk

- `isrc_manager/app_services.py`: 421 LOC.
- No new warning-threshold or mandatory-threshold module was created.
- `ISRC_manager.py` dropped from 27,292 LOC to 26,942 LOC.
- `App` dropped from 26,541 LOC to 26,187 LOC.

## Architecture Metrics Impact

Changed.

Recorded Phase 13 metrics in `architecture_metrics.md`:

- `ISRC_manager.py` LOC: 26,942
- `App` LOC: 26,187
- active compatibility aliases: 42
- root test import count: 8
- module warning threshold count: 34
- module mandatory split threshold count: 11
- import-cycle count: 3
- package parity: unchanged and valid

## QA Checks

Passed:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/app_services.py isrc_manager/tasks/app_services.py`
- `.venv/bin/python -m ruff check isrc_manager/app_services.py`
- Import smoke confirming `initialize_foreground_services`, `configure_foreground_exchange_services`, and `BackgroundAppServiceFactory` import from their separate modules
- `.venv/bin/python -m pytest tests/test_app_bootstrap.py tests/test_background_app_services.py`
- `.venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k startup_first_launch_prompt_can_open_settings_and_clears_pending_flag`
- `.venv/bin/python -m pytest tests/test_migration_integration.py -k background`

Focused pytest results:

- 15 passed
- 1 passed, 34 deselected
- 1 passed, 1 deselected

## QC Checks

- Confirmed Plan 2 Entry Gate passed before editing code.
- Confirmed Engineering Plan 2 Phase 13 scope before editing.
- Confirmed foreground and worker-thread service wiring remain separate.
- Confirmed no Phase 14 profile/session work was performed.
- Confirmed no compatibility inventory entry was required.
- Confirmed no permanent migration glue was introduced.

## Intentionally Not Implemented

- No profile/session controller extraction.
- No diagnostics controller/report extraction.
- No theme/settings/history/app-sound controller extraction.
- No layout, catalog, media, update, or feature workflow controller extraction.
- No root compatibility cleanup.
- No test migration away from root imports.

## Risks / Follow-Up Notes

- `initialize_foreground_services` still receives the live App object as a host seam. Later phases should narrow this as controllers take ownership of profile/session and workflow responsibilities.
- The foreground service graph still depends on profile/session state (`conn`, settings, data roots) until Phase 14 moves that responsibility.
- The pre-existing static import-cycle baseline remains at 3 components and should not increase in later phases.

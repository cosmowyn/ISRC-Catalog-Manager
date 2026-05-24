# Plan 1 Phase 7 Handoff - Settings Dialog Whole Move

Completion timestamp: 2026-05-24 21:37:49 CEST

## Scope Confirmation

Executed only Plan 1 Phase 7 from the Phase 1 prompt set.

The phase was limited to moving `ApplicationSettingsDialog` as a whole and preserving compatibility. No internal settings decomposition, App responsibility extraction, editor work, album/edit dialog work, Phase 8 cleanup, or Plan 2 work was performed.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-7 - Settings Dialog Whole Move.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `tests/test_theme_builder.py`
- `tests/test_qss_autocomplete.py`
- `tests/app/test_app_shell_startup_core.py`

## Files Added

- `isrc_manager/application_settings_dialog.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P1 Phase 7 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/compatibility_inventory.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Moved `ApplicationSettingsDialog` from `ISRC_manager.py` to `isrc_manager.application_settings_dialog`.
- Preserved the root `ISRC_manager.ApplicationSettingsDialog` import as a temporary compatibility alias.
- Kept the dialog implementation intact except for module-level imports required by the move.
- Left `App.open_settings_dialog()` and App smart-history helper call sites on the root compatibility name for now.

## Compatibility Inventory Status

Changed.

Added one active Plan 1 Phase 7 compatibility entry:

- `ISRC_manager.ApplicationSettingsDialog`

The entry has a target path, migration target path, deprecation policy note, dependent runtime/test callers, and planned removal in Plan 2 Phase 21.

Deprecation warnings are deferred because App and tests still construct or inspect the dialog through the root module.

## Root Alias / Wrapper Status

- Root alias additions: one temporary Phase 7 import from `isrc_manager.application_settings_dialog`.
- Root alias removals: none.
- Deprecated wrapper additions/removals: none.
- Permanent migration glue: none.

## Architecture Boundary Observations

- `ISRC_manager.py` no longer locally defines `ApplicationSettingsDialog`.
- The extracted settings dialog module does not import `App`.
- The dialog still depends on existing settings, theme, GS1, QSS, blob icon, app sound, history-budget, and party/owner data modules.
- No long-lived settings/theme/history/app-sound workflow controller was created.
- Phase 8 remains responsible for the internal health pass and any justified UI-only splits.

## Package / Import-Cycle Observations

- Package parity impact: unchanged; the module was added inside the existing `isrc_manager` package.
- Import-cycle risk: low; the extracted module imports feature/service/helper modules but not `ISRC_manager` or `App`.
- Root compatibility import remains temporary and inventoried.

## Module-Size / Mini-Monolith Risk

`isrc_manager/application_settings_dialog.py` is 3,929 LOC and above the mandatory split threshold.

This is expected for the Phase 7 whole-move phase. The risk is tracked in `architecture_metrics.md` and is explicitly handed to Phase 8 for internal health review. No broad settings architecture redesign was performed in Phase 7.

## Architecture Metrics Impact

Changed.

Recorded Phase 7 metrics in `architecture_metrics.md`:

- `ISRC_manager.py` LOC: 30,973
- `App` LOC: 26,543
- active compatibility aliases: 37
- root test import count: 8
- module warning threshold count: 31
- module mandatory split threshold count: 12
- package parity: unchanged

## QA Checks

Passed:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/application_settings_dialog.py`
- `.venv/bin/python -m ruff check isrc_manager/application_settings_dialog.py`
- Root compatibility smoke importing `ApplicationSettingsDialog` from `ISRC_manager`
- `.venv/bin/python -m pytest tests/test_theme_builder.py tests/test_qss_autocomplete.py`
- `.venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k startup_first_launch_prompt_can_open_settings_and_clears_pending_flag`

Focused pytest results:

- 53 passed
- 1 passed, 34 deselected

## QC Checks

- Confirmed the Engineering Plan 1 Phase 7 scope before editing.
- Confirmed the mandatory architecture enforcement requirements before editing.
- Confirmed `ApplicationSettingsDialog` is no longer locally defined in `ISRC_manager.py`.
- Confirmed no `App` import was added to `isrc_manager.application_settings_dialog`.
- Confirmed no Phase 8 internal decomposition was performed.
- Confirmed compatibility inventory changed in the same phase as the new root alias.
- Confirmed no permanent migration glue was introduced.

## Intentionally Not Implemented

- No internal settings dialog tab/panel split.
- No broad settings architecture redesign.
- No settings/theme/history/app-sound workflow controller extraction.
- No App decomposition.
- No album/edit dialog work.
- No CI/import-cycle tooling implementation.
- No removal of temporary root compatibility aliases.

## Risks / Follow-Up Notes

- Phase 8 should review the extracted settings dialog module size and decide whether UI-only helper/tab splits are justified.
- Phase 8 must not turn the settings dialog into a permanent settings/theme/history/app-sound controller surface.

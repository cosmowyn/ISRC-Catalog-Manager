# P1 Phase 1 Handoff

Phase: Plan 1 / Phase 1 - Logging and Prompt Helpers
Completion timestamp: 2026-05-24 21:00:06 CEST
Status: Completed

## What Changed

- Moved the structured trace log formatter implementation from `ISRC_manager.py` to `isrc_manager/app_logging.py`.
- Moved small standalone prompt helper implementations from `ISRC_manager.py` to `isrc_manager/app_prompts.py`.
- Updated `App._configure_logging()` to instantiate the moved `JsonLogFormatter` from the feature module.
- Preserved current root compatibility names needed by existing App call paths and tests.
- Added a focused unit test for `JsonLogFormatter`.
- Updated `compatibility_inventory.md` with Phase 1 root compatibility aliases.
- Updated `architecture_metrics.md` with the Phase 1 metrics record.

## Why It Changed

Phase 1 requires `_JsonLogFormatter` to leave `ISRC_manager.py` and allows truly leaf-level prompt helpers to move when discovered during the batch. The moved prompt helpers are standalone Qt prompt helpers and do not require `App` ownership.

## Files Added

- `isrc_manager/app_logging.py`
- `isrc_manager/app_prompts.py`
- `tests/test_app_logging.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P1 Phase 1 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/compatibility_inventory.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Existing Files Touched And Why

- `ISRC_manager.py`: replaced local formatter/prompt helper implementations with imports or compatibility accessors, and switched trace logging to the extracted formatter.
- `compatibility_inventory.md`: recorded four temporary root compatibility aliases.
- `architecture_metrics.md`: recorded Phase 1 architecture metrics because the phase changed module boundaries and root aliases.
- `Milestones.md`: appended the required Phase 1 milestone entry.

## Scope Control

Scope remained limited to Plan 1 Phase 1. No dialogs, settings UI, waveform/media widgets, catalog panels, license UI, album dialogs, track editor code, or `App` controller decomposition were moved. No Phase 2+ work was performed.

No worker agents were used.

## Intentionally Not Implemented

- No dialog extraction.
- No settings extraction.
- No waveform or media extraction.
- No package configuration changes.
- No CI or import-cycle tooling.
- No broad helper sweep beyond the formatter and three directly adjacent leaf prompt helpers.
- No migration of existing tests away from root `ISRC_manager` imports.

## QA Checks

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/app_logging.py isrc_manager/app_prompts.py` - passed.
- `.venv/bin/python -m pytest tests/test_app_logging.py tests/test_app_bootstrap.py` - 12 passed.
- `.venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'audio_conversion_format_prompt_uses_export_button_label or startup_first_launch_prompt_can_open_settings_and_clears_pending_flag or named_main_window_layouts_can_be_saved_applied_deleted_and_shared_between_menu_and_ribbon'` - 3 passed, 32 deselected.
- `.venv/bin/python` root compatibility smoke checks for `_JsonLogFormatter`, `_prompt_storage_mode_choice`, and `_get_name_from_editable_choice_dialog` - passed.
- `git diff --check` - passed.
- `.venv/bin/python -m ruff check isrc_manager/app_logging.py isrc_manager/app_prompts.py tests/test_app_logging.py` - passed.

Additional note: `python` is not available on this machine. System `python3` can run pure tests but lacks PySide6, so Qt-dependent validation was run with the repository venv. A full `ruff check` including `ISRC_manager.py` reports the existing large import block needs global import reordering; that broad churn was intentionally not applied in this phase.

## QC Checks

- Engineering Plan 1 was read before edits.
- Mandatory architecture enforcement plan was read before edits.
- Live code was inspected for formatter and prompt helper call sites.
- Confirmed no moved module imports `App`.
- Confirmed no new package was created, so package parity was unaffected.
- Confirmed no local definitions remain in `ISRC_manager.py` for `_JsonLogFormatter`, `_get_name_from_editable_choice_dialog`, `_storage_mode_choice_text`, or `_prompt_storage_mode_choice`.
- Confirmed no adjacent phase work was performed.

## Compatibility Inventory Change Status

Changed. Four active root compatibility entries were added:

- `ISRC_manager._JsonLogFormatter` -> `isrc_manager.app_logging.JsonLogFormatter`
- `ISRC_manager._get_name_from_editable_choice_dialog` -> `isrc_manager.app_prompts.get_name_from_editable_choice_dialog`
- `ISRC_manager._prompt_storage_mode_choice` -> `isrc_manager.app_prompts.prompt_storage_mode_choice`
- `ISRC_manager._storage_mode_choice_text` -> `isrc_manager.app_prompts.storage_mode_choice_text`

Each entry has a target path, planned removal phase, current status, and dependent caller/test notes.

## Root Alias Additions Or Removals

- Added temporary root compatibility for `_JsonLogFormatter` through module-level `__getattr__` with a deprecation warning.
- Added temporary root compatibility for `_storage_mode_choice_text` through module-level `__getattr__` with a deprecation warning.
- Preserved `_get_name_from_editable_choice_dialog` and `_prompt_storage_mode_choice` as imported root aliases because current `App` call paths and app-shell tests still monkeypatch those names.
- Removed the local implementations from `ISRC_manager.py`.

## Deprecated Wrapper Additions Or Removals

- Added no wrapper functions or wrapper classes.
- Added module-level compatibility lookup warnings for two root-only private aliases.
- Warning for `_get_name_from_editable_choice_dialog` and `_prompt_storage_mode_choice` is deferred because those aliases are still active internal App globals and app-shell test monkeypatch seams.

## Architecture Boundary Observations

- `isrc_manager/app_logging.py` depends only on standard-library logging/json/date formatting.
- `isrc_manager/app_prompts.py` depends on Qt widgets and file-storage constants; it does not import `App`.
- The extracted modules do not create service-to-UI or controller-to-controller coupling.

## Package Parity Impact

No package parity impact. Phase 1 added modules under the existing `isrc_manager` package and did not create any new package directories.

## Import-Cycle Risk Observations

Low. The new modules do not import `ISRC_manager.py`, and `ISRC_manager.py` imports them as leaf modules. No import-cycle checker exists yet, so the import-cycle count remains unmeasured in `architecture_metrics.md`.

## Module-Size / Mini-Monolith Risk Observations

- `isrc_manager/app_logging.py`: 41 LOC.
- `isrc_manager/app_prompts.py`: 118 LOC.
- Both modules are below the warning threshold and are narrowly scoped.

## Architecture Metrics Impact

Changed. `architecture_metrics.md` now records the Plan 1 Phase 1 metrics:

- `ISRC_manager.py` LOC: 42,854
- `App` LOC: 26,543
- compatibility alias count: 4 active entries
- root import count: 8 Python test imports and 0 `isrc_manager` package imports detected
- package parity: unchanged

## Permanent Migration Glue Confirmation

No permanent migration glue was created. The compatibility aliases are temporary, inventoried, and assigned to Plan 2 Phase 21 for final removal.

## New Compatibility Alias Confirmation

Every new compatibility alias has:

- target path
- deprecation policy or warning-deferral reason
- planned removal phase
- inventory entry

## Risks And Follow-Up Notes

- Phase 2 should not move media prompt behavior as part of visualizer extraction unless directly required by the visualizer scope.
- `_get_name_from_editable_choice_dialog` and `_prompt_storage_mode_choice` remain root monkeypatch seams until internal App call sites and tests migrate.
- Architecture import-cycle tooling remains future work.

## Repo-Specific Conventions Discovered

- Use `.venv/bin/python` for Qt-dependent validation because system `python3` lacks PySide6.
- Existing app-shell tests monkeypatch private root helper names, so root aliases may need to remain active until the related tests migrate.

## Ordered Execution Reconciliation

Re-verified after the Plan 1 Phase 0 reconciliation gate on 2026-05-24 21:09:58 CEST.

Checks rerun:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/app_logging.py isrc_manager/app_prompts.py` - passed.
- `.venv/bin/python -m pytest tests/test_app_logging.py tests/test_app_bootstrap.py` - 12 passed.
- `.venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'audio_conversion_format_prompt_uses_export_button_label or startup_first_launch_prompt_can_open_settings_and_clears_pending_flag or named_main_window_layouts_can_be_saved_applied_deleted_and_shared_between_menu_and_ribbon'` - 3 passed, 32 deselected.
- Root compatibility smoke check for formatter and prompt aliases - passed.

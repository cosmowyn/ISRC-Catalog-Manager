# Smart Storage Budget Footprint Fix

## Summary
Refactored the smart history-storage budget suggestion so it no longer uses only the profile database size. The recommendation now starts from the active profile's Application Storage Admin attribution when available and budgets for the live profile, retained snapshots, one temporary snapshot slot, and a 25% margin.

## User-Facing Result
A 7.3 GB profile with one retained snapshot now suggests 28 GB instead of 11 GB. Storage Admin and Diagnostics also show the safe budget suggestion beside the current profile storage attribution.

## Follow-Up Cleanup
The same pass removed the deprecated catalog-table filter invalidation call and captured expected noisy test logs for mocked migration failures and track deletion progress.

## Changed Files
- `ISRC_manager.py`: smart budget source selection and profile-footprint formula.
- `isrc_manager/app_dialogs.py`: safe budget display in diagnostics and storage admin surfaces.
- `isrc_manager/catalog_table/filter_proxy.py`: Qt filter invalidation compatibility update.
- `tests/test_theme_builder.py`, `tests/test_app_dialogs.py`, `tests/app/_app_shell_support.py`: coverage for budget display and quieter expected log paths.

## Validation
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_theme_builder.py tests/test_app_dialogs.py -q`
- `.venv/bin/python -m black --check ISRC_manager.py isrc_manager/app_dialogs.py tests/test_app_dialogs.py tests/test_theme_builder.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_catalog_table_models.py tests/app/test_app_shell_storage_migration_prompts.py::AppShellStorageMigrationPromptTests::test_schema_migration_error_dialog_suspends_splash_during_startup tests/app/test_app_shell_profiles_and_selection.py::AppShellProfileAndSelectionTests::test_track_delete_progress_reaches_100_only_after_final_ui_refresh -q`

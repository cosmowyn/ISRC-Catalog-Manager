# Master Transfer, Audio Import, History Repair, And Test Stability Handoff

Date: 2026-04-29

## Summary

This pass hardened several catalog migration and media-import paths that were failing too eagerly in real use:

- master catalog transfer export now preflights item-level failures, can proceed with omissions, and writes an omissions log into the ZIP
- master transfer import tolerates missing seeded repertoire references as warnings where possible instead of aborting the entire import
- dropping audio onto an empty catalog now opens a bulk create workflow for new works/tracks using extracted file metadata
- embedded album art from dropped audio files is carried into the create workflow and attached to created tracks
- stale or missing album art preview paths no longer surface as traceback-level failures
- history recovery repair handles missing artifact paths without crashing
- Makefile tooling prefers the project virtualenv and provides a black formatting alias
- theme-builder and contract-template regressions were fixed so focused suites run without the previously reported failures or UI hangs

## Master Catalog Transfer Export

Updated files:

- `ISRC_manager.py`
- `isrc_manager/exchange/master_transfer.py`
- `tests/exchange/test_master_transfer.py`

The master export path now performs a preflight before launching the export. When the preflight finds item-level problems, the UI asks whether to continue. If the user continues, the failing items are omitted from the package and recorded in `export_omissions.log` inside the ZIP for troubleshooting or manual export.

The transfer service now exposes structured export issues and result metadata so the app can report exactly what was skipped. The manifest also reflects omitted items, keeping the archive self-describing instead of silently producing a partial package.

## Master Transfer Import

Updated files:

- `isrc_manager/exchange/repertoire_service.py`
- `tests/exchange/test_repertoire_exchange_service.py`
- `tests/exchange/test_master_transfer.py`

The repertoire importer now degrades unresolved seeded references into import warnings in supported phases instead of failing the whole master import. This addresses cases like:

```text
ValueError: Release reference 27 could not be resolved in the current profile.
```

The import still protects hard integrity requirements, but cross-section references that can be omitted safely are now reported and skipped.

## Dropped Audio Import On Empty Catalogs

Updated files:

- `ISRC_manager.py`
- `isrc_manager/tags/models.py`
- `isrc_manager/tags/service.py`
- `isrc_manager/tags/dialogs.py`
- `isrc_manager/tags/__init__.py`
- `tests/test_tag_service.py`
- `tests/test_tag_dialogs.py`
- `tests/app/test_app_shell_editor_surfaces.py`

Dropping audio files onto an empty catalog now builds a `DroppedAudioImportPlan` from embedded tags and filename fallbacks. The app opens a bulk creation dialog where the user can review and adjust title, artist, album, year, ISRC, duration, and media-storage choices before creating new works and tracks.

The workflow gives the user a clear choice: create new catalog entries from the dropped files or abort the drop action. When accepted, tracks and governed works are created, source audio is attached, releases are synchronized, and embedded album art can be attached as standard album art.

## Embedded Album Art

Updated files:

- `isrc_manager/tags/models.py`
- `isrc_manager/tags/service.py`
- `isrc_manager/tags/dialogs.py`
- `ISRC_manager.py`
- `tests/test_tag_service.py`
- `tests/test_tag_dialogs.py`
- `tests/app/test_app_shell_editor_surfaces.py`

The tag service now extracts embedded artwork from supported audio metadata and carries it through the dropped-audio plan. The dialog exposes whether artwork was found and allows artwork import to be enabled per item. The app materializes selected embedded artwork to a temporary file and attaches it through the normal track media path so the created track behaves like any manually art-attached track.

Album art preview handling was also softened: missing or stale album-art references now show an informational user-facing message instead of logging a traceback like `FileNotFoundError: album_art for track 1`.

## History Repair And Cleanup

Updated files:

- `isrc_manager/history/manager.py`
- `tests/history/_support.py`
- `tests/history/test_history_recovery.py`

History recovery repair now handles entries that have no usable artifact path. This prevents the repair action from crashing with:

```text
TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType'
```

Missing backup diagnostics can now be reported and handled through the recovery/cleanup state machine instead of trapping the user behind a failed repair command.

## Makefile Tooling

Updated file:

- `Makefile`

The Makefile now defaults `PYTHON` to `.venv/bin/python` when the project virtualenv exists, falling back to `python3` otherwise. This fixes local commands that previously used the system Python and failed with missing project tooling, such as:

```text
python3: No module named ruff
```

The file also includes a `black` alias target so formatting can be invoked directly, while `make fix` continues to run Ruff fixes before Black.

## Theme Builder And Contract Template Stability

Updated files:

- `ISRC_manager.py`
- `isrc_manager/contract_templates/dialogs.py`
- `tests/test_theme_builder.py`

Theme application now reapplies menu palettes after repolishing menu chrome, preventing stale application QSS from forcing menu text back to black when saved theme settings are applied without explicit values.

The contract-template HTML preview fit path now uses the WebEngine `contentsSize()` fallback immediately after manual zoom reset. This makes repeated fit-to-view calls stable and fixes the `59 != 100` regression from `test_fit_view_repeats_stably_after_manual_zoom_reset`.

The Application Settings window that appeared during local test runs was traced to stale orphaned test processes rather than an active `make fix` hang. Those old processes were stopped, and the previously stuck app-shell commands now complete normally.

## Validation

Passed focused checks:

- `make fix`
- `./.venv/bin/python -m pytest tests/history/test_history_recovery.py tests/test_history_cleanup_service.py tests/test_tag_service.py tests/test_tag_dialogs.py tests/app/test_app_shell_editor_surfaces.py::AppShellEditorSurfaceTests::test_audio_drop_on_empty_catalog_creates_tracks_and_works_from_metadata tests/exchange/test_repertoire_exchange_service.py tests/exchange/test_master_transfer.py tests/exchange/test_exchange_package.py`
- `./.venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py::AppShellEditorSurfaceTests::test_audio_drop_on_empty_catalog_creates_tracks_and_works_from_metadata tests/app/test_app_shell_editor_surfaces.py::AppShellEditorSurfaceTests::test_audio_drop_on_empty_catalog_imports_embedded_album_art tests/app/test_app_shell_editor_surfaces.py::AppShellEditorSurfaceTests::test_standard_album_art_preview_missing_media_shows_info tests/test_tag_service.py tests/test_tag_dialogs.py`
- `./.venv/bin/python -m unittest tests.test_theme_builder`
- `./.venv/bin/python -m pytest tests/test_theme_builder.py -q`
- `./.venv/bin/python -m unittest tests.contract_templates.test_dialogs -q`
- `./.venv/bin/python -m pytest tests/contract_templates/test_dialogs.py -k "fit_view or html_preview_fit_zoom or reset_to_fit or resize_uses_cached" -q`
- ten repeated runs of `tests.contract_templates.test_dialogs.ContractTemplateWorkspacePanelBehaviorTests.test_fit_view_repeats_stably_after_manual_zoom_reset`
- `./.venv/bin/python -m unittest tests.test_migration_integration -v`
- the previously orphaned app-shell workspace test subset that had left the Application Settings dialog visible
- `git diff --check`

Also passed:

- `py_compile` on touched Python files used by the fixes
- targeted Ruff checks, including `ISRC_manager.py --select F821`
- Black checks for touched non-monolith files

## Remaining Notes

The full 1236-test run was not completed inside this handoff after the earlier Qt callback hang investigation. The user reported the full suite had narrowed to the contract-template fit failure; that failure has since been fixed and verified with the focused full contract-template dialog suite and repeated targeted runs.


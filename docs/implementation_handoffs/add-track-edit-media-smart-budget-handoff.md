# Add Track Layout, Edit Media Duration, And Smart Budget Handoff

Date: 2026-04-26

## Summary

This change set tightens three user-facing workflow areas:

- Add Track draft actions now sit above the tab ribbon so they stay visible without reserving large empty space inside each tab.
- Add Track controls are visually grouped like the Add Works workspace, with containerized sections across the top-level tabs.
- Edit Track now displays database-stored audio files correctly and adds a single-track button to set Track Length from the saved audio file.
- Application Settings now has a Use Smart Budget helper beside Storage Budget. It calculates a practical history budget from the combined size of all profile databases, the retained snapshot count, and a 25% safety margin.

## Files Changed

- `ISRC_manager.py`
  - Reworked Add Track action placement and grouped Add Track controls.
  - Added database-aware audio display fallback in Edit Track.
  - Added `Set Length from Saved Audio` in the Edit Track length group.
  - Added Smart Budget UI and calculation helpers in Application Settings.
- `isrc_manager/main_window_shell.py`
  - Added workspace shortcuts for Add Track and Catalog routes.
- `isrc_manager/help_content.py`
  - Documented the Add Track/Catalog shortcuts and Smart Budget behavior.
- `tests/app/_app_shell_support.py`
  - Updated Add Track layout assertions.
  - Added Edit Track database-audio duration regression coverage.
  - Updated shortcut assertions.
- `tests/app/test_app_shell_editor_surfaces.py`
  - Exposed the new Edit Track database-audio regression test.
- `tests/test_help_content.py`
  - Updated help content expectations for the new shortcuts.
- `tests/test_theme_builder.py`
  - Added Smart Budget coverage for combined multi-profile database sizing.

## Behavior Notes

Edit Track audio display previously only attempted to resolve `audio_file_path`. Database-stored audio usually has no path, so valid stored audio appeared blank in the dialog. The new resolver mirrors the existing album-art fallback and shows the stored filename with a database-storage label.

The new Track Length button uses the existing `TrackService.resolve_media_source()` path. For database blobs it materializes a temporary audio file, reads duration through the existing mutagen-backed duration helper, and fills the hh:mm:ss spin boxes. It does not save until the user saves the dialog.

Smart Budget is intentionally a helper, not an override. It sets the existing Storage Budget field only. Save/Cancel semantics and settings history remain unchanged. The formula is:

`combined profile database bytes * Keep Latest Snapshots * 1.25`, rounded up to a practical MB/GB budget and clamped to supported limits.

## QA Commands

Run with `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` and `QT_QPA_PLATFORM=offscreen` where relevant.

- `python -m tests.ci_groups catalog-services --verify` - passed
- `python -m tests.ci_groups exchange-import --verify` - passed
- `python -m tests.ci_groups history-storage-migration --verify` - passed
- `python -m tests.ci_groups ui-app-workflows --verify` - passed
- CI-style full source compile - passed
- `python -m ruff check build.py isrc_manager scripts tests` - passed
- `python -m black --check build.py isrc_manager scripts tests` - passed after formatting `tests/app/_app_shell_support.py`
- `python -m mypy` - passed
- `python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600` - passed
- `python -m unittest tests.app.test_app_shell_startup_core tests.test_theme_builder tests.test_help_content` - passed, 69 tests
- `python -m unittest tests.app.test_app_shell_editor_surfaces` - passed, 62 tests
- `python -m PyInstaller --version` - passed, reported 6.15.0
- `python -m unittest tests.test_build_requirements -v` - passed, 28 tests
- `git diff --check` - passed

## Local Limitation

`python -m tests.run_group ui-app-workflows --module-timeout-seconds 300 --group-timeout-seconds 2400` was attempted locally. The directly affected editor module completed successfully inside the shard, then the run hit a native Qt WebEngine/Skia segmentation fault in `tests.app.test_app_shell_layout_persistence.AppShellLayoutPersistenceTests.test_contract_template_workspace_named_layout_restore_keeps_import_and_fill_controls_visible`. Re-running that module alone reproduced the same native graphics-context crash before an assertion. This is outside the changed behavior and appears to be a local macOS/offscreen Qt WebEngine runtime issue rather than a Python test assertion failure.

## Follow-Up

If the WebEngine layout-persistence test remains flaky on developer machines, isolate WebEngine-heavy layout persistence coverage into a smaller CI-only or subprocess-guarded path. No code change was made here because the online CI environment is Linux with the workflow's Qt runtime package set, and the changed modules passed their direct coverage locally.

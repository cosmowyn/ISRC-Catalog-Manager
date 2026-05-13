# Media Player Playlist, App Sounds, And Public Docs Handoff

Date: 2026-05-06

## Summary

This change set expands the Audio Player into a stronger catalog auditioning surface, adds app-wide sound-effect controls, wires new playlist control icons, fixes the catalog quick-filter icon rendering, and updates the public documentation surfaces for the media player.

The Audio Player now supports icon-based auto advance, album-scoped playlist playback, shuffle scoped to the active queue, and stop-button visualization fade behavior that matches pause. The catalog search toolbar has a compact selection-filter button that applies the current table cell to the existing search filter. App-wide sound effects now live in a dedicated Sounds settings tab with independent toggles for startup, notice, and warning sounds.

All bundled application sound effects were designed and created by Aeon Cosmowyn.

## User-Facing Changes

- Added `Settings > Application Settings > Sounds` with independent toggles for:
  - startup sound
  - completed-action notice feedback
  - warning/error feedback
- Moved startup sound control out of General and into the new Sounds tab.
- Added sound-effect attribution to the Sounds settings page and help/docs.
- Added `sounds/notice.wav` and `sounds/warning.wav`.
- Notice/warning sounds are played for completed actions and warning/error message paths.
- Added icon-only media player controls for:
  - Auto Advance using `icons/music-note-list.svg`
  - Album Playlist using `icons/collection-play-fill.svg`
- Album Playlist menu includes Off and each album in the profile.
- Selecting an album narrows Play Next to playable tracks from that album and loads the first playable track without starting playback.
- Shuffle now shuffles only the currently available Play Next queue, including album-scoped queues.
- Auto Advance is now a toggle button instead of a checkbox and sits beside the shuffle and album playlist controls.
- Stopping playback now uses the same smooth meter/spectrum release fade as pausing.
- Added `icons/funnel-fill.svg` as the catalog table quick-filter button next to the search reset button.
- The quick-filter button applies the currently selected table cell to the existing search filter.
- Fixed the compact quick-filter icon rendering by capping its icon size and removing inherited global tool-button padding.
- Added `docs/screenshots/media-player.png` and made it the first screenshot in the GitHub README.
- Added a dedicated repository media-player guide at `docs/media-player.md`.
- Updated the in-app help, repository README, docs hub, catalog workflow guide, and GitHub wiki to describe the Audio Player and its capabilities.

## Implementation Notes

- `isrc_manager/app_sounds.py` centralizes sound IDs, filenames, settings keys, defaults, descriptors, and normalization helpers.
- `ISRC_manager.py` now stores app sound settings through the existing `QSettings` path and keeps legacy startup-sound compatibility.
- `ApplicationSettingsTransferService` includes `general.app_sounds` in settings export/import payloads.
- App sound playback uses retained `QSoundEffect` instances and throttled playback for scroll/slider feedback.
- The message-box sound probe uses a stable PySide6 `QMessageBox` class alias so tests or workflows that monkey-patch the module-level `QMessageBox` do not break `isinstance`.
- `_AudioPreviewDialog` now tracks album scope separately from shuffle state and derives the effective queue from the active scope.
- Album-scoped queue building uses database album ordering and filters out tracks that do not have playable media for the current preview source.
- The catalog filter button SVG is tinted to the active button text color, capped at 14 px inside the 20 px toolbar control, and styled with zero padding through the theme stylesheet.
- Build packaging already includes the full `icons/` and `sounds/` directories through the PyInstaller add-data path.

## Documentation

Repository docs updated:

- `README.md`
- `docs/README.md`
- `docs/catalog-workspace-workflows.md`
- `docs/media-player.md`
- `docs/screenshots/media-player.png`

In-app help updated:

- `Application Settings`
- `Audio Player and Image Preview`

Wiki updates prepared in a local clone of `https://github.com/cosmowyn/ISRC-Catalog-Manager.wiki.git`:

- `Home.md`
- `Catalog-Workspace-and-Deliverables.md`
- new `Media-Player.md`

## Tests And Validation

Checks completed during implementation:

- `.venv/bin/python -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py`
- `.venv/bin/python -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py`
- `.venv/bin/python -m ruff check ISRC_manager.py isrc_manager/main_window_shell.py`
- `.venv/bin/python -m ruff check ISRC_manager.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_startup_core.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_app_sound_message_box_probe_uses_stable_qmessagebox_type tests.app.test_app_shell_startup_core.AppShellStartupCoreTests.test_startup_sound_runs_once_after_startup_ready_when_enabled`
- `.venv/bin/python -m py_compile ISRC_manager.py build.py icon_factory.py $(find isrc_manager -name '*.py' | sort) $(find scripts -name '*.py' | sort) $(find tests -name '*.py' | sort)`
- `.venv/bin/python -m ruff check build.py isrc_manager scripts tests`
- `.venv/bin/python -m black --check build.py isrc_manager scripts tests`
- `.venv/bin/python -m mypy`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_help_content tests.test_public_docs tests.test_theme_builder.ThemeBuilderTests.test_application_settings_dialog_exposes_theme_builder_tabs_and_payload tests.test_theme_builder.ThemeBuilderTests.test_stylesheet_covers_expanded_widget_families_and_states tests.test_settings_transfer_service tests.app.test_app_shell_catalog_model_view.AppShellCatalogModelViewTests.test_catalog_table_top_controls_are_grouped_and_shortcut_filters_current_cell tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_audio_preview_layout_groups_and_theme_surfaces_are_exposed tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_audio_preview_navigation_follows_visible_catalog_order_and_auto_advance`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups catalog-services --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups exchange-import --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups history-storage-migration --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups ui-app-workflows --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600 --verbosity 1`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group exchange-import --module-timeout-seconds 120 --group-timeout-seconds 600 --verbosity 1`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group history-storage-migration --module-timeout-seconds 120 --group-timeout-seconds 600 --verbosity 1`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group ui-app-workflows --module-timeout-seconds 300 --group-timeout-seconds 2400 --verbosity 1`
- `git diff --check`

## CI Follow-Up

Pushes to `main` should trigger the `CI` and `Version Bump` workflows. Watch the pushed commit SHA first. If CI fails, inspect the failing GitHub Actions logs through `gh`, reproduce the closest local command, patch the failure, rerun the focused check, commit the fix, push again, and keep watching until all required checks are green.

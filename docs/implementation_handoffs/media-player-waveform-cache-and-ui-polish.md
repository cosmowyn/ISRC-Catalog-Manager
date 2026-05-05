# Media Player Waveform Cache And UI Polish Handoff

Date: 2026-05-05

## Summary

This change set refreshes the audio media player experience and moves static waveform rendering onto a reusable cache path. The player now uses SVG media-control icons, supports off/playlist/track loop states, keeps an existing player window alive instead of reopening it, and updates the ribbon/menu/window icon branding for the media player entry point.

The waveform view now uses cached, frequency/amplitude-colored waveform previews for standard managed audio. Cache validation/generation runs on a dedicated background worker so startup remains responsive after the first analysis pass. Storage diagnostics can detect and clean stale/orphaned cached waveform rows, and track deletion removes related cache rows.

## User-Facing Changes

- Media player transport controls now use SVG icons from `icons/`, including mute/unmute and loop/repeat-one states.
- The media player action in the Catalog > Audio menu and quick action ribbon uses the new media player SVG icon.
- Opening Media Player while a player window already exists brings the existing window back into view.
- A new Application Settings checkbox controls whether `sounds/startup.wav` plays once after the startup splash finishes and the catalog table is visible. Profile switches stay silent.
- Playback layout keeps the top metadata and bottom controls stable while the waveform/artwork stage grows with available space.
- The media player can shrink back to the default dialog size after being enlarged/fullscreened.
- The waveform uses a Traktor-style frequency/amplitude color palette, softened to avoid overpowering the UI.
- Peak meter startup now reads as silence until playback activity begins; peak hold is separate from the live reading and resets only on track restart/new track.
- The playback controls, peak meter, volume slider, mute button, auto-advance checkbox, and Play Next list now share consistent top and bottom alignment anchors, with tighter 8 px control-group margins and a taller control band to reduce dead space. Peak labels are painted inside the peak meter instead of adding extra layout height, and the meter bars start below those labels to avoid overlap.

## Implementation Notes

- `isrc_manager/media/waveform_cache.py` owns waveform cache schema, source fingerprinting, preview rendering, stale/orphan inspection, cleanup, and the daemon-style worker.
- `ISRC_manager.py` wires the background waveform cache worker into startup, track cache scheduling, diagnostics repair, and the media player UI.
- `isrc_manager/services/schema.py` and `isrc_manager/services/tracks.py` include cache schema integration and track deletion/cache scheduling hooks.
- Cached waveform previews include both light and dark themed PNG variants plus raw peaks for fallback/re-render cases.
- The media stage avoids fixed fullscreen-derived sizes; it uses min/max constraints and preferred size hints so the dialog can shrink back to its default footprint.
- The media player quick action icon is deliberately tiny: the actual icon box follows text height, while the SVG glyph is drawn smaller inside that box.
- Startup sound playback is tied to the `startupReady` signal after splash completion, retained through `QSoundEffect`, and packaged from the top-level `sounds/` folder for PyInstaller builds.
- The waveform cache Qt decoder fallback now requires an active `QCoreApplication` before creating `QAudioDecoder`. This prevents headless service tests and non-UI callers from blocking in Qt Multimedia when ffmpeg is unavailable.

## Validation

Full local validation run before push:

- `.venv/bin/python -m compileall -q ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests`
- `.venv/bin/python -m ruff check ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests`
- `.venv/bin/python -m black --check ISRC_manager.py build.py icon_factory.py isrc_manager scripts tests`
- `.venv/bin/python -m mypy`
- `.venv/bin/python -m pip_audit --progress-spinner off -r requirements.txt`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups catalog-services --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups exchange-import --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups history-storage-migration --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups ui-app-workflows --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600 --verbosity 1` passed in 72.84s.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group exchange-import --module-timeout-seconds 180 --group-timeout-seconds 900 --verbosity 1` passed in 11.23s.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group history-storage-migration --module-timeout-seconds 180 --group-timeout-seconds 900 --verbosity 1` passed in 18.33s.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group ui-app-workflows --module-timeout-seconds 300 --group-timeout-seconds 2400 --verbosity 1` passed in 224.30s.
- `.venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py::AppShellStartupCoreTests::test_startup_sound_runs_once_after_startup_ready_when_enabled tests/app/test_app_shell_profiles_and_selection.py::AppShellProfileAndSelectionTests::test_profile_switch_loading_feedback_waits_for_catalog_refresh_completion tests/test_theme_builder.py::ThemeBuilderTests::test_application_settings_dialog_exposes_theme_builder_tabs_and_payload tests/test_settings_transfer_service.py::SettingsTransferServiceTests::test_export_bundle_writes_settings_json_and_attachments tests/test_settings_transfer_service.py::SettingsTransferServiceTests::test_prepare_import_restores_portable_values_and_attachments tests/test_build_requirements.py::CommandConstructionTests::test_pyinstaller_command_bundles_media_icons_and_startup_sounds_when_present`
- `.venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py`
- `.venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py`
- CI follow-up after first push: GitHub Actions exposed a Linux catalog-services timeout in `tests.test_authenticity_verification_service` when service-layer audio cache generation reached the Qt decoder without a Qt application instance. Fixed with the `QCoreApplication` guard and verified with:
  - `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_track_service.py::TrackServiceTests::test_qt_waveform_decoder_is_skipped_without_application_instance tests/test_authenticity_verification_service.py::AudioAuthenticityVerificationServiceTests::test_export_provenance_audio_reports_real_progress_stages_before_terminal_completion -q`
  - `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600 --verbosity 1` passed in 72.46s.
  - `.venv/bin/python -m compileall -q isrc_manager/media/waveform_cache.py tests/test_track_service.py`
  - `.venv/bin/python -m ruff check isrc_manager/media/waveform_cache.py tests/test_track_service.py`
  - `.venv/bin/python -m black --check isrc_manager/media/waveform_cache.py tests/test_track_service.py`
  - `.venv/bin/python -m mypy`

Raw unsharded `.venv/bin/python -m pytest` was not used as the final local signal because native macOS Qt modal handling can hang outside the CI runner shape. The CI-style `tests.run_group` runner was used instead with `QT_QPA_PLATFORM=offscreen` and module/group timeouts, matching the online workflow more closely.

Test harness note: `tests/app/_app_shell_support.py` now patches both informational and duplicate-track warning message boxes in the governed child-track workflow so the offscreen CI runner cannot block on an advisory modal dialog.

## CI Notes

Pushes to `main` should trigger the `CI` and `Version Bump` workflows. A successful version bump may trigger release metadata updates and, if tagged, release-build workflow handling. Watch the pushed commit SHA first, then watch any follow-up bot commit from the version bump workflow.

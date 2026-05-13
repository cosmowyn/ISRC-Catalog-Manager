# Media Player Bookmarks, EQ Pan, and Visual Release Handoff

Date: 2026-05-13

## Scope

- Removed the scroll/click sound from the app, including the bundled sample, settings transfer surface, settings UI option, and runtime triggers.
- Added per-track media bookmarks from the media player. The bookmark button can save the current playhead, jump to saved timestamps, and remove individual or all bookmarks.
- Added persistent equalizer panning and compacted the EQ dialog layout so the graph remains aligned with the sliders.
- Added double-click reset support for EQ sliders and the media player volume slider.
- Fixed spectrum and peak-meter release behavior so pause, stop, and natural end-of-file all decay instead of freezing the last rendered frame.
- Refreshed media button icon state handling so enabled icons repaint crisply after startup/waveform loading state transitions.

## Implementation Notes

- Bookmark persistence lives in `isrc_manager.media.bookmarks.TrackAudioBookmarks` and the `audio_bookmarks` table created by `DatabaseSchemaService.init_db`.
- Bookmark rows are keyed by `track_id`, `position_ms`, and `label`; track deletion cleanup is handled by the existing foreign-key cascade.
- Waveform bookmark markers are UI-only overlays derived from the current track's stored timestamps.
- EQ pan is stored with the other media EQ settings and applied in `EqualizerPlayer` by setting per-channel audio output volume.
- Visualizer release is preserved during pause/end-state position sync by letting the release animation own the spectrum and peak gain until playback resumes.
- The old scroll/click sound setting is intentionally absent from exported settings bundles and the in-app settings panel.

## Verification

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m py_compile ISRC_manager.py build.py icon_factory.py $(find isrc_manager -name '*.py' | sort) $(find scripts -name '*.py' | sort) $(find tests -name '*.py' | sort)`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m ruff check build.py isrc_manager scripts tests`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m black --check build.py isrc_manager scripts tests`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m mypy`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups catalog-services --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups exchange-import --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups history-storage-migration --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.ci_groups ui-app-workflows --verify`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group exchange-import --module-timeout-seconds 180 --group-timeout-seconds 900`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group history-storage-migration --module-timeout-seconds 180 --group-timeout-seconds 900`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group ui-app-workflows --module-timeout-seconds 300 --group-timeout-seconds 2400`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pip_audit --progress-spinner off -r requirements.txt`

All local checks passed before staging.

## Follow-Up

- Watch the online GitHub Actions CI after pushing to confirm the Python 3.10, 3.13, and 3.14.4 matrix remains green.

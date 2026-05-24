# Plan 1 Phase 3 Handoff - Media Preview Dialogs

Completion timestamp: 2026-05-24 21:21:44 CEST

## Scope Confirmation

Executed only Plan 1 Phase 3 from the Phase 1 prompt set.

Phase scope was limited to moving media preview dialogs, audio preview preload/result data structures, and audio preview preload helper functions out of `ISRC_manager.py` while preserving current behavior through temporary root compatibility imports.

No album/edit dialog extraction, catalog manager work, settings work, controller decomposition, or Plan 2 work was performed.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-3 - Media Preview Dialogs.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `ISRC_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_catalog_model_view.py`

## Files Added

- `isrc_manager/media/preview_dialogs.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P1 Phase 3 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/compatibility_inventory.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed

- Moved `_ImagePreviewDialog` to `isrc_manager.media.preview_dialogs`.
- Moved `_HiDpiArtworkLabel` to `isrc_manager.media.preview_dialogs`.
- Moved `_AudioPreviewDialog` to `isrc_manager.media.preview_dialogs`.
- Moved audio preview preload/result data classes and helper functions to `isrc_manager.media.preview_dialogs`.
- Added temporary root compatibility imports in `ISRC_manager.py` for moved preview classes and helpers.
- Updated existing Phase 2 visualizer compatibility rows to record that preview dialogs now import visualization/waveform targets directly.
- Added Phase 3 compatibility inventory rows for the moved preview classes, data structures, and helpers.
- Recorded Phase 3 architecture metrics.

## Compatibility Inventory Status

Changed.

Added 19 active Plan 1 Phase 3 compatibility entries:

- `ISRC_manager._ImagePreviewDialog`
- `ISRC_manager._HiDpiArtworkLabel`
- `ISRC_manager._AudioPreviewDialog`
- `ISRC_manager._AudioPreviewPreloadBridge`
- `ISRC_manager._AudioPreviewPreloadCancelled`
- `ISRC_manager._AudioPreviewPreparedMedia`
- `ISRC_manager._AudioPreviewPreloadTask`
- `ISRC_manager._AudioPreviewPreloadResult`
- `ISRC_manager._AudioPreviewTrackLoadTask`
- `ISRC_manager._AudioPreviewTrackLoadResult`
- `ISRC_manager._audio_preview_detect_mime_from_bytes`
- `ISRC_manager._audio_preview_suffix_for_mime`
- `ISRC_manager._audio_preview_fetch_source_for_preload`
- `ISRC_manager._audio_preview_write_preload_temp_file`
- `ISRC_manager._audio_preview_artwork_payload_for_snapshot`
- `ISRC_manager._audio_preview_track_queue_items_for_service`
- `ISRC_manager._audio_preview_state_for_preload_task`
- `ISRC_manager._build_audio_preview_preload`
- `ISRC_manager._build_audio_preview_track_load`

All entries have target paths, migration target paths, deprecation policy notes, and planned removal in Plan 2 Phase 21.

Deprecation warnings are deferred for these root aliases because `_ImagePreviewDialog` and `_AudioPreviewDialog` remain live construction seams for `App`, and the root module remains a broad app-shell import seam in current tests. No permanent migration glue was introduced.

## Root Alias / Wrapper Status

- Root alias additions: 19 temporary Phase 3 imports from `isrc_manager.media.preview_dialogs`.
- Root alias removals: none.
- Deprecated wrapper additions/removals: none.
- Permanent migration glue: none.

## Architecture Boundary Observations

- `ISRC_manager.py` no longer locally defines the Phase 3 preview dialogs or audio preview preload helpers.
- The extracted preview module does not import `App`.
- Media responsibility separation was preserved:
  - visualization remains in `isrc_manager.media.waveform` and `isrc_manager.media.audio_visualization`
  - preparation/preload helpers moved with the preview surface
  - playback remains delegated to `LiveEqualizerPlayer`
  - export execution remains delegated to existing App callbacks/actions
- Existing waveform cache, equalizer, equalizer player, and bookmark modules are reused.
- The extraction did not pull preview dialogs into a controller module.

## Package / Import-Cycle Observations

- Package parity impact: unchanged; `isrc_manager.media` already exists in package configuration.
- Import-cycle risk: no direct `App` import was introduced in the extracted module. Compile/import smoke passed for root and extracted modules.
- The root module still imports temporary compatibility names from `isrc_manager.media.preview_dialogs`; these are inventoried for Plan 2 Phase 21 removal.

## Module-Size / Mini-Monolith Risk

`isrc_manager/media/preview_dialogs.py` is 3,963 LOC after the move and is above the mandatory split threshold recorded in `architecture_metrics.md`.

This is a tracked risk, not a hidden exception. The module is large because Phase 3 scope requires moving the live preview dialog and its preload/result helpers together. It does not own the complete media platform because visualization, equalizer playback, bookmarks, waveform cache access, and export execution remain separated.

## Architecture Metrics Impact

Changed.

Recorded Phase 3 metrics in `architecture_metrics.md`:

- `ISRC_manager.py` LOC: 36,831
- `App` LOC: 26,543
- active compatibility aliases: 31
- root test import count: 8
- module warning threshold count: 30
- module mandatory split threshold count: 11
- package parity: unchanged/valid by filesystem package check

## QA Checks

Passed:

- `.venv/bin/python -m compileall ISRC_manager.py isrc_manager/media/preview_dialogs.py`
- `.venv/bin/python -m ruff check isrc_manager/media/preview_dialogs.py`
- Root compatibility smoke importing moved preview symbols from `ISRC_manager`
- `.venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py tests/app/test_app_shell_catalog_model_view.py -k audio_preview`

Focused pytest result:

- 7 passed, 70 deselected

## QC Checks

- Confirmed the Engineering Plan 1 Phase 3 scope before editing.
- Confirmed the mandatory architecture enforcement requirements before editing.
- Confirmed moved definitions are no longer locally defined in `ISRC_manager.py`.
- Confirmed no `App` import was added to the extracted preview module.
- Confirmed Phase 3 did not perform adjacent Phase 4+ work.
- Confirmed compatibility inventory changed in the same phase as root alias additions.
- Confirmed no source behavior changes were intended beyond relocation and imports.

## Intentionally Not Implemented

- No media-player feature work.
- No waveform extraction beyond Phase 2.
- No App decomposition.
- No album/edit dialog extraction.
- No catalog manager work.
- No CI/import-cycle tooling implementation.
- No removal of temporary root compatibility aliases.

## Risks / Follow-Up Notes

- `isrc_manager/media/preview_dialogs.py` should be watched closely because it exceeds the mandatory split threshold.
- Phase 4 should avoid touching media preview responsibilities.
- Plan 2 Phase 19D should use the extracted media boundaries and must not pull preview dialogs back into media controller modules.

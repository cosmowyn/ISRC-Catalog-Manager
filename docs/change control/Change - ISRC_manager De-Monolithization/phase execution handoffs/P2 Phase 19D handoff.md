# P2 Phase 19D Handoff - Media Player, Bookmarks, Equalizer, Waveform Cache Orchestration, and Audio Export Controllers

Completion timestamp: 2026-05-24 23:51 CEST

## Scope Executed
- Executed Plan 2 Phase 19D only.
- Moved audio waveform cache service/worker queue orchestration out of `App`.
- Moved media player action icon, media player opening, audio/image preview opening, preview state assembly, preview navigation, and raw/blob preview routing out of `App`.
- Moved media file export, focused media-column export, catalog audio copy export, and tagged audio export preparation out of `App`.
- Preserved existing preview dialogs, waveform cache service/worker, equalizer dialog/settings/player, and audio bookmark infrastructure in their established media modules.

## Files Inspected
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`
- `ISRC_manager.py`
- `isrc_manager/media/preview_dialogs.py`
- `isrc_manager/media/waveform_cache.py`
- `isrc_manager/media/equalizer.py`
- `isrc_manager/media/equalizer_player.py`
- `isrc_manager/media/bookmarks.py`
- `isrc_manager/catalog_table/context_menu.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_catalog_model_view.py`
- `tests/app/_app_shell_support.py`
- `tests/test_track_service.py`
- `tests/test_tag_service.py`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Files Added
- `isrc_manager/media/waveform_cache_worker.py`
- `isrc_manager/media/player_controller.py`
- `isrc_manager/media/export_controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19D handoff.md`

## Compatibility Inventory Status
- Unchanged.
- No compatibility aliases were added, changed, migrated, or removed.
- Active alias count remains 42.
- Every active alias remains planned for removal in Plan 2 Phase 21.

## Media Architecture Gate
- Visualization remains in `isrc_manager.media.audio_visualization` and `isrc_manager.media.waveform`.
- Preparation/preload and preview dialog UI remain in `isrc_manager.media.preview_dialogs`.
- Playback and equalizer playback infrastructure remain in `isrc_manager.media.equalizer_player`, with equalizer settings/dialog behavior still in `isrc_manager.media.equalizer`.
- Bookmark infrastructure remains in `isrc_manager.media.bookmarks`.
- Export orchestration now lives in `isrc_manager.media.export_controller`.
- No single media module owns visualization, preparation/preload, playback, and export.
- Preview dialogs were not moved into the controller modules.

## Architecture Boundary Observations
- New media controllers import no root `ISRC_manager` module.
- Root-patched test seams are preserved through lazy root attribute lookups for message boxes, file dialogs, tag preview dialog, preview dialog aliases, and file-history helper calls.
- `isrc_manager.media.export_controller` is 1,175 LOC, below the warning threshold but close enough to monitor during future media changes.
- Phase 19D did not create permanent migration glue; the remaining `App` methods are delegation shims for the ongoing Plan 2 decomposition.

## Package Parity and Import-Cycle Status
- Package parity unchanged and valid: 27 pyproject packages match 27 filesystem packages.
- No package visibility change was required because all new modules are inside the existing `isrc_manager.media` package.
- Static import-cycle count remains at the baseline of 3.
- No `isrc_manager` package module imports `ISRC_manager`.

## Validation
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/media/player_controller.py isrc_manager/media/export_controller.py isrc_manager/media/waveform_cache_worker.py`
- `.venv/bin/python -m ruff check isrc_manager/media/player_controller.py isrc_manager/media/export_controller.py isrc_manager/media/waveform_cache_worker.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY' ... import isrc_manager.media.player_controller/export_controller/waveform_cache_worker ... PY`
- `rg -n "from ISRC_manager|import ISRC_manager|ISRC_manager\\." isrc_manager/media/player_controller.py isrc_manager/media/export_controller.py isrc_manager/media/waveform_cache_worker.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py -k 'export_catalog_audio_copies or export_standard_audio_file_embeds_catalog_metadata or bulk_audio_column_export_uses_background_task_and_embeds_catalog_metadata or media_player_action or audio_preview'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_catalog_model_view.py -k 'audio_preview_navigation or focused_audio_export'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_track_service.py -k 'waveform_cache'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tag_service.py`

## Results
- Compile passed.
- Ruff passed.
- Import smoke passed.
- Root-import scan returned no matches.
- Focused app-shell media/export tests passed: 10 passed, 56 deselected.
- Focused app-shell catalog media-routing tests passed: 2 passed, 9 deselected.
- Waveform cache service tests passed: 5 passed, 45 deselected.
- Tag export service tests passed: 17 passed.

## Remaining Risks Before Phase 19E
- Audio conversion, watermarking, authenticity, and provenance orchestration still live on `App` and should be moved in Phase 19E.
- Some Phase 19E methods depend on export target helpers that now delegate through `isrc_manager.media.export_controller`; focused conversion/authenticity tests should cover those crossings.
- Existing root-patched app-shell tests still require root import migration before Phase 21 can remove aliases and wrappers.

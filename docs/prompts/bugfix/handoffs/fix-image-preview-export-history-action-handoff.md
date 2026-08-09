# Completion Handoff

## Original prompt

Fix the Image Preview export failure shown in the supplied screenshots. After choosing a destination for **Export Image…** and clicking **Save**, the application reports:

`'App' object has no attribute '__run_file_history_action'`

## Result

- Corrected the extracted media export controller to call the real `App._run_file_history_action` contract instead of the nonexistent double-underscore attribute.
- Updated the controller regression test so it can no longer mask the production typo.
- Strengthened the real App-shell Image Preview test to choose an export path, click the actual export control, write the exact image bytes, route `file.export_image_preview` through file history, report success, and avoid the critical-error path.
- Extended `UI-PQ-MEDIA-001` with a deterministic PNG fixture, real Image Preview export, byte/size/SHA-256 verification, file-history routing evidence, error-count evidence, a captured Image Preview surface, and updated traceability.
- Kept Help text and committed Help screenshots unchanged because they already document Image Preview export accurately and no visible UI changed.

## Files changed

- `isrc_manager/media/export_controller.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/traceability.py`
- `tests/app/_app_shell_support.py`
- `tests/test_media_export_controller.py`
- `tests/ui_qa/test_ui_pq_media_audio_workflow.py`
- `docs/prompts/bugfix/fix-image-preview-export-history-action.md`
- `docs/prompts/bugfix/handoffs/fix-image-preview-export-history-action-handoff.md`

## Verification

Passed:

- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_media_export_controller.py --no-cov` — 17 passed.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_media_preview_preload.py::test_image_preview_dialog_zoom_export_gesture_and_artwork_label_paths --no-cov` — 1 passed.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/app/test_app_shell_editor_surfaces.py::AppShellEditorSurfaceTests::test_image_preview_supports_zoom_gestures_fit_reset_and_export --no-cov` — 1 passed.
- `ISRC_UI_PQ_COMPONENTS='["media-audio"]' ISRC_UI_PQ_ARTIFACT_DIR='build/ui-pq-image-preview-export-governor' QT_QPA_PLATFORM=offscreen python3 -m pytest -q --no-cov tests/ui_qa/test_ui_pq_media_audio_workflow.py tests/ui_qa/test_ui_pq_traceability.py` — 2 passed.
- `ISRC_UI_PQ_ARTIFACT_DIR='build/ui-pq-full-image-preview-export' QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/ui_qa --no-cov` — 32 passed, including the Help gate.
- `python3 -m compileall ISRC_manager.py isrc_manager tests` — passed on Python 3.14.4.
- `python3 -m ruff check build.py isrc_manager scripts tests` — passed.
- `python3 -m black --check build.py isrc_manager scripts tests` — 655 files unchanged.
- `python3 -m mypy` — no issues in 50 source files.
- `git diff --check` — passed.

Known unrelated validation limitations:

- `QT_QPA_PLATFORM=offscreen python3 -m tests.run_group ui-app-workflows --module-timeout-seconds 120 --group-timeout-seconds 600` was attempted twice. Both runs completed the first 67 modules successfully, including all 66 App-shell editor-surface tests, then `tests.test_theme_builder` timed out after 120 seconds in `test_apply_theme_without_explicit_values_uses_saved_theme_settings`. That exact test passed when run independently.
- The full UI PQ command against the existing default `artifacts/ui_pq` root encountered 26 stale visual-baseline mismatches in unrelated accounting, SoundCloud, authenticity, and repertoire surfaces. The same complete suite passed against the fresh artifact root recorded above. Verification-generated changes to tracked artifacts and Help screenshots were restored because they are unrelated to this non-visual fix.

## Prompt archive

- `docs/prompts/bugfix/fix-image-preview-export-history-action.md`
- `docs/prompts/bugfix/handoffs/fix-image-preview-export-history-action-handoff.md`

## Follow-up actions

- Investigate the pre-existing `tests.test_theme_builder` order-dependent timeout separately from this media export fix.
- Decompose `isrc_manager/media/export_controller.py` in a dedicated refactor. It was already 1,177 lines before this task; this fix changes one character and does not increase its size.
- Review the analogous pre-existing `self.__run_snapshot_history_action` call in `isrc_manager/promo_codes/controller.py` as a separate promo-ledger bug fix.

## Notes

- No dependency, schema, database migration, or public API change was introduced.
- The one-character production correction restores the method name used before the media controller extraction and preserves file-history rollback behavior.
- The generated full-suite Help screenshots were intentionally not retained because the UI layout and documented workflow did not change.
- Four generated default-root Image Preview PQ files were moved to `/tmp/isrc-image-preview-pq-generated-20260809` during workspace cleanup; they are recoverable there for the current system session.

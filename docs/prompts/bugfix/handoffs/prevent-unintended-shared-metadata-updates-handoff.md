# Completion Handoff

## Original prompt

When I update track metadata, for example the album title, unrelated records also get updated on save, causing a gigantic mess in the database.

Investigate why and propose a production-safe fix. Before overwriting shared metadata such as album title or UPC, show the linked tracks that will receive the new values and allow individual tracks to be unchecked. Also restore automatic canonical ISRC generation for tracks created through drag and drop, and add a manual canonical ISRC generation button to Track Edit.

## Result

- Confirmed the root cause: legacy album rows are resolved by title, so unrelated releases with the same title can share one `album_id`; Track Edit then treated that concrete group as authoritative and silently propagated album-level fields.
- Added an explicit shared-metadata review before any write. It identifies the edited source track, lists linked peers with context, checks peers initially, and lets the operator exclude individual records or cancel without writing.
- Revalidates the source revision, album-group identity, exact membership, and every selected peer revision inside the write transaction before mutation.
- Moves the source and checked peers into a fresh album group, keeps excluded tracks in the original group, retains same-title group isolation on later ordinary edits, preserves legacy fallback artwork on both sides of a split, and deletes only an exact old group after it becomes unused.
- Restricts automatic release synchronization to safe membership matches. Curated or mismatched releases are left unchanged for explicit review instead of being split, expanded, or duplicated.
- Restored automatic ISRC generation for blank drag/drop rows. Generated codes are batch-unique and reservation-aware across profiles; all claims and temporary artwork are released on validation, reservation, scheduling, or worker failure.
- Kept the drag/drop controller below the repository's production-module limit by isolating candidate generation and cross-profile reservation in a focused ISRC helper.
- Added **Generate New ISRC** to single-track edit. It uses the canonical generator, confirms replacement of an existing code, and reserves the changed code at save.
- Updated Help and UI PQ traceability for both recovery paths and the shared-metadata review.

## Files changed

- `isrc_manager/help_content.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/traceability.py`
- `isrc_manager/releases/controller.py`
- `isrc_manager/selection_scope.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/tags/metadata_controller.py`
- `isrc_manager/tags/dropped_audio_isrc.py`
- `isrc_manager/tracks/edit_dialog.py`
- `isrc_manager/tracks/host_protocols.py`
- `tests/test_help_content.py`
- `tests/test_release_controller.py`
- `tests/test_selection_scope.py`
- `tests/test_tags_metadata_controller.py`
- `tests/test_track_service.py`
- `tests/tracks/test_edit_dialog_behaviors.py`
- `tests/ui_qa/test_ui_pq_catalog_workflow.py`
- `docs/prompts/bugfix/prevent-unintended-shared-metadata-updates.md`
- `docs/prompts/bugfix/handoffs/prevent-unintended-shared-metadata-updates-handoff.md`

## Verification

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --no-cov -q tests/test_track_service.py tests/test_release_controller.py tests/test_tags_metadata_controller.py tests/tracks/test_edit_dialog_behaviors.py tests/test_selection_scope.py tests/test_help_content.py tests/ui_qa/test_qa_helpers.py tests/app/test_app_shell_editor_surfaces.py` — 212 passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group catalog-services --module-timeout-seconds 120 --group-timeout-seconds 600` — all 103 modules completed successfully.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group exchange-import --module-timeout-seconds 300 --group-timeout-seconds 2400` — completed successfully.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group history-storage-migration --module-timeout-seconds 300 --group-timeout-seconds 2400` — completed successfully.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.run_group ui-app-workflows --module-timeout-seconds 300 --group-timeout-seconds 2400` — all 95 modules completed successfully.
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager tests` — passed.
- `.venv/bin/python -m ruff check build.py isrc_manager scripts tests` — passed.
- `.venv/bin/python -m black --check build.py isrc_manager scripts tests` — 615 files unchanged.
- `.venv/bin/python -m mypy` — no issues in 50 source files.
- `git diff --check` — passed.
- The screenshot-regenerating UI PQ qualification command was not run against the user's dirty checkout because its evidence and screenshot outputs already contained unrelated user changes. The complete non-mutating CI group matrix was instead run from an isolated clean worktree.

## Prompt archive

- `docs/prompts/bugfix/prevent-unintended-shared-metadata-updates.md`
- `docs/prompts/bugfix/handoffs/prevent-unintended-shared-metadata-updates-handoff.md`

## Follow-up actions

- Existing incorrectly linked production rows are not destructively migrated or guessed apart. Review suspicious linked peers when the new dialog appears, or repair known legacy groupings through an explicitly reviewed maintenance workflow.
- `isrc_manager/help_content.py`, `isrc_manager/qa/scenarios.py`, `isrc_manager/services/tracks.py`, and `isrc_manager/tracks/edit_dialog.py` already exceeded the repository's 1000-line production-module limit before this task. Decompose them along help-topic, QA-scenario, album-group service, and shared-edit workflow boundaries in separate dedicated refactors; broad decomposition inside this production data fix would have increased release risk.

## Notes

- No schema migration or production-database write is required. Dependency maintenance and publication are handled as separately reviewed repository operations.
- Checkboxes intentionally start selected because the requested workflow is to uncheck tracks that must not change; the modal requires an explicit **Update Selected Tracks** action.
- Same-title creation remains backward compatible. The safety boundary is now concrete `album_id` membership plus reviewed subset isolation; later ordinary updates retain the current group instead of resolving by title again.
- Existing unrelated workspace changes and generated QA artifacts were preserved.

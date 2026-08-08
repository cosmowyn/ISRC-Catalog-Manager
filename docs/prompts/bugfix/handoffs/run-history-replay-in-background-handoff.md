# Completion Handoff

## Original prompt

> Undo and Redo work, but when redoing, the app appears hung because the process operates on the UI thread. Offload the process to a worker thread with a truthful, updating progress bar to inform the user that the work is still in operation.

## Result

Catalog/profile-database Undo and Redo now run through the existing background-task system using a worker-local database connection. Replay is exclusive and non-cancellable, blocks duplicate commands and conflicting automatic history work, and reports monotonic determinate progress only as concrete replay phases finish. The bar reaches 100% only after the committed result has been synchronized and rendered by the UI.

History-dialog replay owns its progress window and no longer performs a stale immediate refresh. Worker failures resynchronize the visible history state before reporting the error. The shared task relay also defers cleanup during success finalization so reentrant Qt event processing cannot close the progress surface before its terminal update.

## Files changed

- `isrc_manager/history/replay_controller.py`
- `isrc_manager/history/replay_progress.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/history/dialogs.py`
- `isrc_manager/history_retention_controller.py`
- `isrc_manager/main_window.py`
- `isrc_manager/tasks/manager.py`
- `isrc_manager/help_content.py`
- `isrc_manager/qa/harness.py`
- `isrc_manager/qa/scenarios.py`
- `isrc_manager/qa/traceability.py`
- `tests/history/test_snapshot_replay_scope.py`
- `tests/test_history_replay_controller.py`
- `tests/test_history_dialogs.py`
- `tests/test_history_retention_controller_clusters.py`
- `tests/test_main_window_helpers.py`
- `tests/test_task_manager.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_profiles_and_selection.py`
- `tests/ui_qa/test_qa_helpers.py`
- `tests/ui_qa/test_ui_pq_history_replay.py`
- `tests/ui_qa/test_ui_pq_traceability.py`
- `tests/ci_groups.py`
- Regenerated governed UI-PQ evidence and Help screenshots under `artifacts/ui_pq/` and `docs/help/screenshots/`.

## Verification

- Full history replay plus party/right and asset-delete history suites passed.
- The history/storage/migration CI group completed successfully across 54 modules.
- Focused controller, dialog, retention, task-relay, and main-window tests passed.
- Real Qt worker-thread tests proved that the UI event loop remains responsive during a deliberately blocked Redo, duplicate replay is rejected, UI callbacks retain main-thread affinity, and 100% is emitted only after interface refresh.
- UI-PQ-HIST-001 and its full qualification harness passed; Help and traceability tests passed.
- CI ownership verification passed for the history/storage/migration and UI/application groups.
- Full Ruff, Black, configured mypy, compileall, and `git diff --check` passed.

## Prompt archive

- `docs/prompts/bugfix/run-history-replay-in-background.md`
- `docs/prompts/bugfix/handoffs/run-history-replay-in-background-handoff.md`

## Follow-up actions

- Profile lifecycle session actions remain UI-bound because they directly coordinate profile navigation and file replacement. Moving those actions requires a separate filesystem-plan/UI-finalization split; catalog record Undo/Redo, including the reported delete/redo path, is backgrounded now.
- `isrc_manager/history/manager.py` remains an oversized pre-existing production module. The new UI orchestration and progress policy were extracted into focused modules, but further decomposition should be handled separately.

## Notes

- No new dependency was introduced.
- Progress represents completed replay phases rather than elapsed-time guesses.
- Existing shared-worktree changes from the earlier credential-reset and destructive-history work were preserved.

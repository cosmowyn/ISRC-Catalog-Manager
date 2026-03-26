# True Progress Lifecycle Unification

## Scope

This pass was limited to import/export progress truthfulness and terminal-completion semantics.

It did not introduce a second progress system or redesign unrelated import/export architecture.

## Stale / Fake Progress Paths Found

- `export_repertoire_exchange()` still had an old synchronous export path for JSON/XLSX/CSV before the newer background-task shell, which meant stale or misleading progress behavior.
- Catalog exchange export used the shared task dialog, but the export services were not reporting real staged progress.
- Party export used the shared task dialog, but the export services were not reporting real staged progress.
- XML export used the shared task dialog, but the export service was not reporting real staged progress.
- Repertoire/package export did not expose real staged export progress through the shared task contract.

## Post-100% Hidden Work Found

- `BackgroundTaskManager` delivered `on_success` before task cleanup, so UI work could run while the task dialog still represented a completed worker.
- `_submit_background_bundle_task()` previously completed its nominal worker phase before the bundle-close boundary was represented in progress semantics.
- Import success handlers in `ISRC_manager.py` were still doing meaningful UI-thread work after worker-side `100%` progress:
  - catalog import apply/refresh/history updates
  - Party import apply/refresh/history updates
  - repertoire import apply/refresh/history updates
  - tag import apply/refresh/history updates
  - repair-row reapply apply/refresh work
- History capture/record work from `run_snapshot_history_action()` and `run_file_history_action()` was previously outside the visible staged lifecycle.

## Export Progress Changes Made

- Added real staged export progress to:
  - catalog exchange export
  - Party export
  - repertoire/contracts-and-rights export
  - XML export
- Export workers now report:
  - row/payload collection
  - row preparation / serialization
  - file or package writing
  - history capture / history record
  - terminal completion after bundle-close
- Removed the leftover direct synchronous JSON/XLSX/CSV repertoire export path so the background-task flow is now the only export path there.

## Import Completion Lifecycle Changes Made

- Added shared progress-scaling helpers in `ISRC_manager.py` so service progress occupies the worker portion of the lifecycle and UI apply/finalization occupies the tail.
- Import flows now reserve the final progress band for:
  - history snapshot capture
  - history record
  - background bundle close / commit boundary
  - UI-thread apply / refresh / focus / history refresh
- For catalog import, Party import, repertoire import, tag import, and repair replay:
  - worker/service progress no longer claims terminal completion too early
  - UI-thread finalization is now represented explicitly before `100%`
  - the final dialog close happens only after those steps complete
- Import inspection tasks for catalog exchange and Party exchange now open the next dialog after cleanup instead of while the progress dialog is still alive.

## Shared Lifecycle Contract Established

All touched import/export progress dialogs now follow one contract:

- service or worker stages report monotonic progress
- history capture and record are part of the visible lifecycle
- bundle-close / transaction-finalization is represented before completion
- UI-thread apply / refresh work is represented before completion when it is part of readiness
- `100%` is emitted only at terminal completion
- follow-up success UI runs after cleanup, not during the still-active task dialog

In practice this now uses:

- worker-side service progress scaled into the early/middle range
- history-helper progress hooks for post-mutation bookkeeping
- `worker_completion_progress` only after bundle scope exits
- `on_success_before_cleanup` for truthful UI-thread finalization stages
- `on_success_after_cleanup` for post-completion notifications/dialogs

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/tasks/manager.py`
- `isrc_manager/tasks/history_helpers.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/parties/exchange_service.py`
- `isrc_manager/exchange/repertoire_service.py`
- `isrc_manager/services/exports.py`
- `tests/test_task_manager.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_json.py`
- `tests/test_party_exchange_service.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/test_repertoire_exchange_service.py`
- `tests/test_xml_export_service.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`

## Tests Added / Updated

- Added manager-level lifecycle ordering coverage proving:
  - pre-cleanup finalization runs while the task is still active
  - post-cleanup success runs only after dialog cleanup
- Added export staged-progress coverage for:
  - catalog exchange JSON export
  - Party JSON export
  - repertoire JSON export
  - XML export
- Kept and revalidated staged import-progress coverage for:
  - catalog exchange import
  - Party import
  - repertoire import
- Added app-shell regression proving repertoire export uses the background-task path instead of an old direct synchronous export call.

Validation run:

- `python3 -m unittest tests.test_task_manager tests.exchange.test_exchange_json tests.test_party_exchange_service tests.exchange.test_repertoire_exchange_service tests.test_xml_export_service tests.app.test_app_shell_workspace_docks`
- `python3 -m black --check ISRC_manager.py isrc_manager/tasks/manager.py isrc_manager/tasks/history_helpers.py isrc_manager/exchange/service.py isrc_manager/parties/exchange_service.py isrc_manager/exchange/repertoire_service.py isrc_manager/services/exports.py tests/test_task_manager.py tests/exchange/_support.py tests/exchange/test_exchange_json.py tests/test_party_exchange_service.py tests/exchange/_repertoire_exchange_support.py tests/exchange/test_repertoire_exchange_service.py tests/test_xml_export_service.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py`

## Remaining Limitations / Next Bottlenecks

- This pass focused on import/export data workflows and the shared background-task contract they use. Other long-running preview-style flows outside that scope may still be candidates for the same before-cleanup/after-cleanup pattern.
- Some success handlers still do lightweight logging/audit UI work after cleanup; that work is intentionally kept after terminal completion because it no longer represents operation readiness.
- If future work moves more final UI refresh work off the main thread, the same lifecycle contract should still be preserved rather than shortened artificially.

## Explicit Completion Statement

For the import/export progress dialogs touched in this pass, `100%` now means true completion.

The dialog does not reach terminal completion until:

- real worker/service processing is done
- history capture/record work is done
- bundle-close / commit work is done
- any required UI-thread apply/refresh work for readiness is done

There is no longer a hidden long-running tail after the dialog claims completion.

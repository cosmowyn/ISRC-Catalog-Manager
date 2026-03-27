# 3.1.0 Follow-up: Export, Docs, and History Path Fix

## Summary

This pass prepared the application for `3.1.0` by tightening the export target contract, fixing a directory-vs-file history crash, restoring predictable export filename behavior, and refreshing user-facing documentation so it matches the current product state.

## 1. Version Bump Locations Updated

The application version was updated to `3.1.0` in the surfaced runtime and packaging locations:

- `pyproject.toml`
- `ISRC_manager.py`
- `isrc_manager/tasks/app_services.py`

Supporting test expectations were updated in:

- `tests/test_build_requirements.py`
- `tests/test_app_dialogs.py`

User-facing version banners were updated in:

- `README.md`
- `demo/README.md`
- `license.md`
- `docs/file_storage_modes.md`
- `docs/repertoire_knowledge_system.md`
- `docs/gs1_workflow.md`
- `docs/theme_builder.md`
- `docs/modularization_strategy.md`
- `docs/undo_redo_strategy.md`

## 2. Stale Docs Found And Updated

The docs refresh focused on areas that no longer matched the current application behavior:

- `README.md`
  - updated authenticity menu paths to the current `Catalog > Audio` structure
  - removed the outdated claim that authenticity exports stay reviewable in `Derivative Ledger`
  - updated import wording to reflect the current inspect/review/apply contract
  - updated startup-loading wording to match the truthful progress work
- `docs/import-and-merge-workflows.md`
  - replaced the outdated three-path framing
  - documented the shared preview/review/apply import contract
  - added Party and Contracts/Rights import coverage
  - updated the `Reset Saved Import Choices…` menu path
  - removed the stale standalone XML user-flow framing
- `docs/audio-authenticity-workflow.md`
  - updated command names to the current menu structure
  - removed the outdated `Derivative Ledger` review claim
  - clarified that authenticity exports are file-and-sidecar outputs, not ledger-registered managed derivatives
- `docs/catalog-workspace-workflows.md`
  - updated audio workflow menu paths
  - clarified that authenticity exports do not create `Derivative Ledger` rows
- `docs/README.md`
  - updated the import guide summary
  - removed outdated authenticity-ledger wording
- `docs/diagnostics-and-recovery.md`
- `docs/undo_redo_strategy.md`
  - corrected overstatements around cleanup protection for ordinary backups and aged pre-restore safety copies

## 3. Contract Export Filename-Generation Fix

Two export surfaces were corrected so they always resolve a concrete output file or folder target before writing:

- Repertoire / Contracts and Rights export in `ISRC_manager.py`
  - JSON, XLSX, and ZIP exports now open with timestamped default filenames under the app exports directory
  - CSV bundle export now opens from the app exports directory and resolves to a concrete timestamped bundle folder name
- Contract document and deadline exports in `isrc_manager/contracts/dialogs.py`
  - contract document export now resolves a directory-like selection into the suggested document filename
  - deadline CSV export now opens with a default filename and resolves directory-like selections into a concrete CSV path

## 4. Root Cause Of The Directory/File Export Crash

The failing crash path was:

1. `Export Contracts and Rights CSV Bundle…` used `QFileDialog.getExistingDirectory(...)`
2. the returned directory path was passed unchanged into `run_file_history_action(...)`
3. `run_file_history_action(...)` called `HistoryManager.capture_file_state(...)`
4. `capture_file_state(...)` attempted `shutil.copy2(...)` on that directory path
5. Python raised `IsADirectoryError`

The underlying bug was not only the traceback line. The real contract bug was that one export workflow treated a directory selection as if it were already a file artifact target.

## 5. Shared Export/History Guardrails Added

The fix was split between caller-side correction and shared seam hardening.

### Caller-side export target resolution

Added shared helpers in `isrc_manager/file_storage.py`:

- `resolve_file_export_target(...)`
- `resolve_directory_export_target(...)`

These are now used so export callers resolve the final file or folder target before write/history logic runs.

### Shared history guardrails

`isrc_manager/history/manager.py` now rejects directory targets for:

- `capture_file_state(...)`
- `restore_file_state(...)`

This prevents similar directory/file mistakes from silently slipping into file-history logic or recursive rollback paths.

### Export-history contract correction

- File-based exports still use `run_file_history_action(...)`
- Directory-oriented CSV bundle export now uses `run_snapshot_history_action(...)` instead of pretending a directory is a file artifact

That keeps history/audit behavior intact while respecting the actual artifact type.

## 6. Tests Added/Updated

Focused regression coverage was added or updated for:

- version surfacing and staged artifact naming
- contract document export resolving a directory selection to a concrete filename
- file-history helper rejection of directory targets before mutation runs
- repertoire export resolving directory-like selections into real file targets
- repertoire CSV bundle export using snapshot-style history instead of file-history capture

Touched tests:

- `tests/test_build_requirements.py`
- `tests/test_app_dialogs.py`
- `tests/history/_support.py`
- `tests/history/test_history_action_helpers.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/catalog/test_contract_service.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`

Validated locally with:

- `python3 -m unittest tests.history.test_history_action_helpers tests.catalog.test_contract_service tests.app.test_app_shell_workspace_docks tests.test_build_requirements tests.test_app_dialogs`
- `python3 -m unittest tests.exchange.test_repertoire_exchange_service tests.exchange.test_exchange_json tests.test_party_exchange_service tests.test_xml_export_service`
- `python3 -m black --check ISRC_manager.py isrc_manager/file_storage.py isrc_manager/history/manager.py isrc_manager/contracts/dialogs.py isrc_manager/tasks/app_services.py tests/history/_support.py tests/history/test_history_action_helpers.py tests/catalog/_contract_rights_asset_support.py tests/catalog/test_contract_service.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py tests/test_build_requirements.py tests/test_app_dialogs.py`

## 7. Risks / Caveats

- The new history guard rejects directory targets explicitly. Any future export workflow that truly writes a directory bundle must use snapshot-style history or another directory-aware history model instead of file-history capture.
- User-facing docs were refreshed where the behavior was clearly stale, but historical implementation handoffs were intentionally left alone.
- The contract/repertoire export naming now uses timestamped defaults; any future product naming changes should reuse the shared target-resolution helpers instead of reintroducing raw path handling.

## 8. Explicit Final Statement

Export now resolves a real file target before history capture.

File-history capture no longer accepts raw directory paths as file artifacts, and the Contracts and Rights CSV bundle export no longer routes directory targets through file-history at all.

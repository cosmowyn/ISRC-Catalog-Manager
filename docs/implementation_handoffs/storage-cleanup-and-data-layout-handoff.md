# Storage Cleanup And Data Layout Handoff

## Confirmed current storage behavior

- `settings.ini` and the single-instance lock are now resolved through Qt-managed app settings paths from [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py).
- App-owned writable data is resolved separately through `AppStorageLayout.preferred_data_root`, with portable mode still keeping everything beside the executable.
- The active app-owned storage tree now uses one root with these managed subdirectories:
  - `Database/`
  - `backups/`
  - `history/`
  - `logs/`
  - `exports/`
  - `help/`
  - `track_media/`
  - `release_media/`
  - `licenses/`
  - `contract_documents/`
  - `asset_registry/`
  - `custom_field_media/`
  - `gs1_templates/`
- `HistorySnapshots` stores full SQLite snapshot copies plus optional managed-directory snapshot manifests.
- `HistoryBackups` stores registered backup metadata and file paths.
- `HistoryEntries` stores snapshot archive references, file-state bundle references, and reversible history metadata.
- `history/session_history.json` stores app-level profile lifecycle undo/redo state and points to `history/session_profile_snapshots/`.

## Root causes

- Non-portable app-owned data previously used a Windows-shaped `LOCALAPPDATA/<AppName>` style path on every platform.
- Qt settings and lock files already used `QStandardPaths`, which split the writable layout across two unrelated roots.
- Snapshot growth was unbounded because manual snapshots, auto snapshots, snapshot archives, file-state bundles, and pre-restore safety backups all accumulated without any in-app retention workflow.
- The first migration implementation copied SQLite `.db` files as plain files. That could miss committed WAL content or copy an inconsistent file if a managed profile had a live writer or lingering journal files.
- Diagnostics-triggered migration could run while the current managed profile was still bound in the foreground app, which increased the risk of copying a database while it was active.
- Migration cannot be treated as a raw directory move because history metadata embeds absolute paths in:
  - `HistorySnapshots.db_snapshot_path`
  - `HistorySnapshots.settings_json`
  - `HistorySnapshots.manifest_json`
  - `HistoryBackups.backup_path`
  - `HistoryBackups.source_db_path`
  - `HistoryBackups.metadata_json`
  - `HistoryEntries.payload_json`
  - `HistoryEntries.inverse_json`
  - `HistoryEntries.redo_json`
  - `history/session_history.json`
  - snapshot and backup sidecars

## Implemented storage layout

- Centralized path resolution now lives in [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py).
- `AppStorageLayout` is the source of truth for:
  - `settings_root`
  - `settings_path`
  - `lock_path`
  - `preferred_data_root`
  - `active_data_root`
  - `legacy_data_roots`
  - standard app-owned subdirectories
- Qt application identity is applied before any `QStandardPaths` lookup so macOS, Windows, and Linux all resolve to app-specific vendor/app containers.
- Runtime services in [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py), [`isrc_manager/main_window_shell.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/main_window_shell.py), [`isrc_manager/app_dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/app_dialogs.py), [`isrc_manager/tasks/app_services.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tasks/app_services.py), and [`isrc_manager/services/gs1_settings.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/gs1_settings.py) now use the resolved active data root instead of hardcoded `DATA_DIR()` assumptions.

## Migration flow

- Migration logic lives in [`isrc_manager/storage_migration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_migration.py).
- Detection is staged:
  - preferred layout already populated: continue normally
  - legacy layout detected and preferred layout empty: prompt the user
  - portable mode: skip migration
- Startup prompt options:
  - `Migrate Now`
  - `Keep Current Folder For Now`
- Deferral writes:
  - `storage/legacy_data_root`
  - `storage/active_data_root`
  - `storage/migration_state = deferred`
- Migration behavior:
  - blocks migration while background tasks are still running
  - closes the active foreground profile connection before a diagnostics-triggered migration begins
  - stages copied content into a temporary sibling root on the same volume
  - copies SQLite databases with SQLite's backup API instead of raw file copies
  - skips transient SQLite companion files such as `-wal`, `-shm`, and `-journal`
  - validates that every expected staged file is present before promotion
  - verifies copied databases with `PRAGMA integrity_check`
  - rewrites embedded paths inside migrated metadata
  - promotes the staged root into the preferred location only after copy, rewrite, and verification all succeed
  - leaves the legacy root intact
  - writes a journal file at `<preferred_root>/storage_migration.json`
- Failure behavior:
  - leaves the legacy root untouched
  - keeps the failed staging area for inspection
  - writes a fallback failure journal beside the preferred root so diagnostics can still report the last failed attempt even when promotion never happened
- After a successful migration, the app rebinds to the migrated profile if the current profile database lived inside the old managed `Database/` subtree.

## Migration journal format

- Journal path: `<preferred_data_root>/storage_migration.json`
- Failure fallback journal path: `<preferred_data_root.parent>/.<preferred_data_root.name>_storage_migration.json`
- Current fields:
  - `status`
  - `app_name`
  - `source_root`
  - `target_root`
  - `stage_root`
  - `copied_items`
  - `source_inventory_count`
  - `rewritten_files`
  - `verified_databases`
  - `started_at`
  - `completed_at`
  - `failed_at`

## Cleanup behavior

- Cleanup logic lives in [`isrc_manager/history/cleanup.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/cleanup.py).
- Cleanup preview classifies items as:
  - eligible
  - protected
- Eligible cleanup classes currently include:
  - unreferenced live snapshot rows/files
  - registered backup rows/files
  - orphan snapshot files
  - orphan backup files
  - unreferenced snapshot archive bundles
  - unreferenced file-state bundles
  - stale session profile snapshots
- Protected cleanup classes currently include:
  - snapshots still referenced by history entry snapshot columns or payload snapshot IDs
  - snapshot archive bundles still referenced by retained snapshot history payloads
  - file-state bundles still referenced by retained history payloads
  - session profile snapshots still referenced by `session_history.json`
- Blocking cleanup issues currently include:
  - stale current history head
  - missing snapshot artifacts
  - missing snapshot archives
  - missing backup files
  - missing backup history artifacts
  - dangling snapshot references
- Orphan-only findings do not block cleanup; they appear as eligible items instead.

## Trim history behavior

- The trim operation keeps:
  - the most recent user-selected count of visible reversible entries on the active applied branch
  - the current default redo branch
- The trim operation then:
  - deletes older `HistoryEntries`
  - normalizes history invariants
  - deletes newly unreferenced snapshot rows/files
  - deletes newly unreferenced snapshot archive bundles
  - deletes newly unreferenced file-state bundles

## UI surfaces

- [`isrc_manager/history/dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/dialogs.py)
  - adds a `Backups` tab to `HistoryDialog`
  - adds a `Cleanup…` dialog for preview, selected deletion, and trim workflow
- [`isrc_manager/app_dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/app_dialogs.py)
  - Diagnostics now exposes a `Storage layout` check
  - repair action label follows the active check, including `Migrate App Data`
- Existing object names and main dialog hooks were preserved:
  - `historyDialog`
  - `diagnosticsDialog`
  - `applicationLogDialog`

## Tests added or updated

- Added:
  - [`tests/test_paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_paths.py)
  - [`tests/test_storage_migration_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_storage_migration_service.py)
  - [`tests/test_history_cleanup_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_history_cleanup_service.py)
- Updated:
  - [`tests/test_history_dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_history_dialogs.py)
  - [`tests/test_gs1_settings_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_gs1_settings_service.py)
  - [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)

## Targeted verification run

- `python3 -m unittest tests.test_paths tests.test_storage_migration_service tests.test_history_cleanup_service tests.test_history_dialogs tests.test_gs1_settings_service`
- `python3 -m unittest tests.test_app_shell_integration.AppShellIntegrationTests.test_startup_can_defer_legacy_storage_migration_and_keep_current_folder tests.test_app_shell_integration.AppShellIntegrationTests.test_startup_builds_main_window_with_core_actions`

## Remaining limitations and recommended follow-up

- The cleanup dialog currently presents eligible/protected items in a generic table. If users need richer storage accounting, add per-category totals and human-readable size summaries.
- Diagnostics exposes storage migration and history repair, but there is not yet a dedicated storage-usage dashboard.
- Trim-history preview is count-based and example-based. A future enhancement could show the exact retained branch cut-off and projected disk savings before confirmation.
- The targeted tests cover the new path, migration, cleanup, and startup defer flows. The full app-shell suite remains slower in this environment, so broader UI regression runs are still recommended before release packaging.

# Storage Migration Reliability Fix

## Status And Scope

This handoff is a reliability follow-up to [`storage-cleanup-and-data-layout-handoff.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md). It does not replace the baseline storage-layout design. It documents the migration reliability regression, the repaired startup control flow, and the new adoption and retry rules.

Scope stayed limited to:

- startup root selection
- storage migration recovery and adoption
- migration observability
- regression coverage for the repaired flow

This pass did not change unrelated schema, catalog logic, cleanup semantics, history semantics, or portable-mode behavior.

## Source Of Truth

The baseline storage rules from the earlier handoff still stand:

- managed subdirectories and active data-root rules
- rewrite surfaces inside history, snapshot, backup, and session metadata
- migration journal naming and location
- safety rules against destructive overwrite and unsafe path rewrites

Keep using these files together:

- [`docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md)
- [`docs/diagnostics-and-recovery.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/diagnostics-and-recovery.md)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/storage_migration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_migration.py)
- [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py)

## Confirmed Root Causes

1. Startup migration ran before logging bootstrap, and `_run_storage_layout_migration()` logged success before `self.logger` and `self.trace_logger` were configured.
2. Startup chose or inherited an active root before migration reconciliation, then later bootstrapped directories, help content, history state, logs, and `default.db` under that root.
3. `storage/active_data_root` could stay pinned to legacy after a deferred or failed migration, so the next launch recreated managed legacy files even when the preferred root already held valid migrated data.
4. Preferred-root readiness was reduced to `bool(target_items)`, which treated any non-empty preferred root as “ready” but still let promotion fail on any non-empty target.
5. The migration service already preserved failure journals and `stage_root`, but startup and diagnostics did not consume them for adoption or resume.
6. Post-copy startup errors could reclassify a successful migration as failure and send the app back to legacy.

## Broken Pre-Fix Sequence

Old startup order was:

1. open settings
2. resolve storage layout
3. inspect or run startup migration
4. only then configure file logging
5. create active-root directories
6. create help content and session-history storage
7. open or create `default.db`

That sequence created two bad outcomes:

- a successful service migration could still crash on the first `_log_event()` because logging was not bootstrapped yet
- once settings pointed back at legacy, later startup recreated legacy data before any adoption or recovery logic could correct the root

## Repaired Startup And Migration Sequence

New startup order is:

1. open settings
2. create bare logger objects and an in-memory bootstrap log buffer
3. resolve an initial layout only to construct the migration service
4. run `_reconcile_startup_storage_root()` before any managed-data writes
5. let startup choose exactly one launch root:
   - portable root
   - adopt verified preferred root
   - resume preserved `stage_root`
   - fresh migrate from legacy into preferred
   - honor explicit defer to legacy
   - keep legacy when preferred has conflicting content
6. resolve and apply the final layout with `active_data_root=chosen_root`
7. configure file logging for that final root
8. flush buffered migration and startup log events into the final log files
9. continue with help, history, database, and background bootstrap

Diagnostics repair now uses the same service entrypoint as startup, so adopt, resume, and fresh migration share the same safety rules.

## Active / Preferred / Legacy Root Rules

- `preferred_data_root` remains the intended managed app-data destination.
- `legacy_data_root` remains the legacy managed location used only for detection, copy source selection, and explicit defer behavior.
- `active_data_root` is still a stored setting, but startup no longer treats it as authoritative before reconciliation.
- [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py) stays a pure layout builder. It does not inspect migration validity.
- Startup reconciliation is now the place that can override stale `storage/active_data_root` and stale `storage/migration_state`.
- Portable mode still bypasses migration and uses the portable root directly.

## Destination Assessment And Adoption Rules

Preferred-root state is now classified as one of:

- `empty`
- `valid_complete`
- `resumable_stage`
- `safe_noise`
- `conflict`

`valid_complete` means:

- required source-backed managed content exists in preferred
- required content is `Database`, `history`, `backups`, `exports`, plus any managed storage subdirectories that existed in legacy or the migration journal
- `logs` and `help` are optional and never required for validity
- every `.db` in preferred passes `PRAGMA integrity_check`
- known rewrite surfaces no longer contain absolute paths under legacy
- a complete journal is supporting evidence when present, but not the sole signal

`safe_noise` is intentionally narrow:

- empty directories
- `logs/**`
- the generated help file

Any non-validated `.db`, history payload, backup payload, export payload, or managed media/document file is treated as `conflict`, not noise.

When preferred is `valid_complete`, startup and diagnostics adopt it automatically and refresh settings to use preferred.

## Retry / Resume / Recovery Semantics

- The migration service is now the authoritative recovery entrypoint.
- When preferred is `valid_complete`, `migrate()` adopts without copying and returns `action="adopted"`.
- When a preserved fallback journal and `stage_root` exist and the stage validates, `migrate()` resumes by promoting the preserved stage and returns `action="resumed"`.
- When preferred is `empty` or `safe_noise`, `migrate()` performs the existing stage, copy, rewrite, verify, and promote flow and returns `action="migrated"`.
- When preferred is `conflict`, `migrate()` raises a conflict error naming the blocking preferred-root items and does not overwrite anything.
- If a preserved stage cannot be resumed safely but legacy is still available, the service falls back to a fresh staged migration from legacy.
- `mark_failed()` no longer rewrites `storage/active_data_root`, which avoids pinning future launches to legacy before reconciliation.
- `defer()` still records explicit user choice to keep legacy active, but startup will still auto-adopt preferred later if preferred already validates complete.

## Legacy Recreation Rules

- Legacy managed files are only recreated when legacy is the deliberate authoritative root for that launch.
- Once preferred has been adopted or migrated successfully, startup no longer recreates managed files under legacy just because settings were stale.
- Manual deletion of legacy after successful migration is now stable: startup can keep using preferred without rebuilding legacy scaffolding.
- This pass does not auto-delete legacy data.

## Logging And Diagnostics Expectations

- Migration is observable from the first startup attempt.
- Before file handlers are configured, migration and startup events are buffered in memory.
- After the final root is selected, buffered events are flushed into that root’s application and trace logs.
- Important logged stages now include:
  - startup reconciliation decision
  - adopt
  - resume
  - fresh stage/copy
  - safe-noise cleanup
  - promote
  - failure journal write
  - startup deferral
  - startup conflict fallback

## Tests Added Or Updated

Updated or added coverage in:

- [`tests/test_storage_migration_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_storage_migration_service.py)
- [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)

Covered scenarios now include:

- first-launch `Migrate Now` startup flow with working logging bootstrap
- verified preferred-root auto-adoption even when settings still pin legacy
- preserved staged migration resume without recopying
- safe preferred-root bootstrap residue cleanup
- conflicting non-empty preferred-root block behavior
- manual legacy cleanup after adoption without legacy recreation
- external absolute paths staying untouched during path rewrite
- defer flow staying internally consistent between active root and DB settings
- portable-mode startup skipping migration and legacy adoption

## Remaining Limits / Future Follow-Up

- Conflicting preferred-root content is still a hard safety stop and requires manual resolution or diagnostics-guided investigation.
- This pass does not add automatic legacy cleanup or removal after successful migration.
- The diagnostics UI now benefits from the repaired flow, but it still reports conflicts as text rather than providing a richer conflict-resolution workflow.
- Migration logs are now buffered safely during startup, but there is still room for a more explicit migration-status UI if the app needs it later.

## Reference Appendix

### Prior Docs

- [`docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md)
- [`docs/diagnostics-and-recovery.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/diagnostics-and-recovery.md)

### Key Code Surfaces

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/storage_migration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_migration.py)
- [`isrc_manager/paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/paths.py)

### Key Tests

- [`tests/test_storage_migration_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_storage_migration_service.py)
- [`tests/test_app_shell_integration.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_app_shell_integration.py)
- [`tests/test_paths.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_paths.py)

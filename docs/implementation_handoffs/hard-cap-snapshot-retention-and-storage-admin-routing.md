# Hard-Cap Snapshot Retention And Storage-Admin Routing

## Summary

This pass turns snapshot retention into a hard-cap policy, centralizes storage-size math and formatting, raises the storage-budget ceiling to `1 TB`, fixes the budget spinbox stepping/display behavior, and routes over-budget prompts to `Application Storage Admin` instead of `History Cleanup`.

It is intentionally stricter than earlier history-cleanup behavior:

- manual snapshots now participate in the same retained-snapshot cap as automatic and helper snapshots
- the configured retained-snapshot count is authoritative for live snapshots, except when the current visible undo boundary itself requires more live snapshots than the cap
- older history entries that lose required artifacts are quarantined in place instead of being silently kept alive forever

This preserves immediate last-action undo for the current visible undo boundary while allowing older reversibility to be retired when that is necessary to respect the retention cap.

## Previous Handoffs Reviewed

This implementation was checked against these earlier handoffs before changing behavior:

- [`storage-cleanup-and-data-layout-handoff.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md)
- [`application-wide-storage-admin-and-final-cleanup.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/application-wide-storage-admin-and-final-cleanup.md)

This patch intentionally changes two earlier assumptions:

- manual snapshots are no longer protected indefinitely
- final cleanup of protected history artifacts now quarantines dependent history entries in place instead of deleting those entries outright

Those changes do not corrupt prior intended logic. They refine it so settings remain truthful, cleanup becomes deterministic, and final admin cleanup still avoids creating new history/session artifacts.

## Files And Layers Touched

- [`isrc_manager/history/cleanup.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/cleanup.py)
- [`isrc_manager/history/manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/manager.py)
- [`isrc_manager/history/__init__.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/__init__.py)
- [`isrc_manager/storage_admin.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_admin.py)
- [`isrc_manager/storage_sizes.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_sizes.py)
- [`isrc_manager/ui_common.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/ui_common.py)
- [`isrc_manager/constants.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/constants.py)
- [`isrc_manager/services/settings_reads.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/settings_reads.py)
- [`isrc_manager/services/settings_mutations.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/settings_mutations.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/app_dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/app_dialogs.py)
- [`isrc_manager/history/dialogs.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/history/dialogs.py)
- [`README.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/README.md)

Test coverage was updated in:

- [`tests/test_history_cleanup_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_history_cleanup_service.py)
- [`tests/test_storage_admin_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_storage_admin_service.py)
- [`tests/test_storage_sizes.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_storage_sizes.py)
- [`tests/test_ui_common.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_ui_common.py)
- [`tests/test_theme_builder.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_theme_builder.py)
- [`tests/test_settings_read_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_settings_read_service.py)
- [`tests/test_settings_mutations_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_settings_mutations_service.py)
- [`tests/test_settings_transfer_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_settings_transfer_service.py)
- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)

## Retention Contract

### Live snapshots

In this patch, a **live snapshot** means:

- a `HistorySnapshots` row
- its snapshot database file
- its snapshot sidecar
- its snapshot companion files such as `-journal`
- its snapshot assets root and managed-directory copies

This does not include archived snapshot bundles, file-state bundles, session leftovers, or orphaned artifacts that are no longer authoritative for restore/undo.

### Enforcement rule

Retention now runs through `HistoryStorageCleanupService.enforce_snapshot_retention(...)`.

The survivor order is:

1. compute the live snapshots required by `HistoryManager._visible_undo_snapshot_ids()`
2. count those protected snapshots inside the configured `auto_snapshot_keep_latest` cap, not in addition to it
3. if protected snapshots are fewer than the cap, fill the remaining slots from newest remaining live snapshots
4. prune all remaining older live snapshots oldest-first

### Overflow rule

If the current visible undo boundary needs more live snapshots than the configured cap:

- the visible undo boundary wins
- only that protected set is retained
- no extra snapshots are kept
- `HistorySnapshotRetentionResult.cap_limited_by_visible_undo` is set to `True`

This is the only case where the retained live-snapshot count can exceed the nominal user cap.

### Undo safety

Immediate undo safety is preserved at the current visible undo boundary only.

That means:

- the current visible undo plan remains reversible
- older history entries can lose reversibility if their artifacts are pruned
- explicit snapshot/backup/history-artifact deletion actions remain exempt from artifact preservation

This is an explicit non-goal boundary for the patch: it does not preserve arbitrary older undo/redo history when doing so would violate hard-cap retention.

## Quarantine And Cleanup Behavior

### In-place quarantine

Retention and admin cleanup now use `HistoryManager._quarantine_artifact_references(...)` as the shared repair path.

Quarantine mutates `HistoryEntries` in place:

- `reversible` becomes `0`
- `status` becomes `artifact_missing`
- `snapshot_before_id` and `snapshot_after_id` are cleared when they point at pruned snapshots
- `snapshot_id` values inside payload, inverse payload, and redo payload are scrubbed
- payload paths under the profile snapshot-archive and file-state roots are scrubbed when the entry becomes affected

No synthetic replacement history entries are created.

If the current history head points into a quarantined visible-undo chain, the head is moved to the nearest visible unaffected ancestor or the existing fallback selector result.

### Cleanup order

Pruning now follows this deterministic sequence:

1. compute protected visible-undo live snapshots
2. compute survivor set inside the cap
3. identify pruned live snapshots
4. quarantine affected history references in place
5. delete pruned `HistorySnapshots` rows
6. delete their snapshot DB files, sidecars, companion files, asset roots, and managed-directory copies
7. run orphan cleanup for newly unreferenced snapshot archives, file-state bundles, orphan snapshot bundles/companions, orphan backup companions, and stale session snapshot leftovers
8. re-run history invariant enforcement

This prevents stale references from surviving after the storage artifact is removed.

## Storage Budget Model

All size math is now centralized in [`isrc_manager/storage_sizes.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/storage_sizes.py).

### Internal units

- persistence remains in `history_storage_budget_mb` for compatibility
- conversion is binary and exact:
  - `1 MB = 1024 * 1024 bytes`
  - `1 GB = 1024 MB`
  - `1 TB = 1024 GB`

### Supported range

- minimum budget stays `128 MB`
- maximum budget is now `1_048_576 MB` (`1 TB`)

Reads clamp numeric values and fall back to the default when the stored value is invalid/non-numeric. Writes clamp to the supported range.

### Display rules

Budget text is now human-readable and centralized:

- below `1024 MB`: whole `MB`
- `1 GB` to under `1 TB`: `GB`
- `1 TB` and above: `TB`

`GB` and `TB` display use up to 2 decimal places with half-up rounding and trailing zero trimming.

## Budget Spinbox Behavior

The settings dialog now uses `StorageBudgetSpinBox` instead of a plain `QSpinBox`.

Behavior:

- values are stored as whole MB internally
- typed input accepts `MB`, `GB`, and `TB`
- input is case-insensitive
- optional whitespace is allowed
- `.` and `,` decimal separators are accepted
- parsed values round to the nearest MB and then clamp

Step behavior:

- normal step: `1 MB`
- during press-and-hold auto-repeat: first `10 MB` of repeated held movement use `1 MB`
- after that threshold, repeated held movement switches to `100 MB`
- release, key-up, mouse-up, or focus loss resets stepping back to `1 MB`
- decrement is symmetrical

## Presets And Settings Truthfulness

Retention presets now include storage budget in their payload matching.

The settings UI now flips to `custom` when any of these diverge from an exact preset tuple:

- retention mode payload
- auto-cleanup enabled
- storage budget
- retained-snapshot count
- pre-restore prune days

If the full tuple later matches a preset again, the preset auto-selects again.

## Over-Budget Routing

Over-budget prompts now route to `Application Storage Admin` consistently.

Updated flows include:

- projected-growth preflight
- post-action budget enforcement
- startup/history refresh driven budget warnings
- manual snapshot and restore preflight paths that call the shared helpers
- settings-change enforcement through the same budget hooks

`HistoryCleanupDialog` remains available as an explicit history-management tool, but it is no longer the authoritative over-budget resolution surface.

## Application Storage Admin Changes

`ApplicationStorageAdminService` now inventories and removes additional orphan classes so the admin view matches the cleanup engine:

- orphan snapshot asset roots
- orphan snapshot companion files
- orphan backup companion files
- session snapshot `-journal` companions

Protected-history cleanup through Storage Admin now:

- quarantines dependent history entries in place
- removes the storage artifact directly
- avoids creating new history or session entries
- refreshes history action state after successful admin cleanup

The `StorageAdminCleanupResult.removed_history_entry_ids` field name is unchanged for compatibility, but the ids now refer to quarantined dependent entries rather than deleted ones.

## QC Checks Performed

- verified retention enforcement now operates on all live snapshots, not just auto snapshots
- verified protected visible-undo snapshots count inside the cap
- verified the overflow case reports `cap_limited_by_visible_undo=True`
- verified pruned snapshots are removed oldest-first
- verified pruned snapshot DBs, assets roots, and companion files are deleted
- verified snapshot-create history entries become `artifact_missing` and non-reversible in place when their snapshot is pruned
- verified shared storage-size helpers format MB/GB/TB consistently
- verified settings reads clamp/fallback correctly and writes clamp correctly at the new max
- verified the settings dialog budget control round-trips human-readable values
- verified held stepping accelerates to `100 MB` and resets after release
- verified projected-growth prompts open `Application Storage Admin`
- removed stale wording that claimed manual restore points stay protected by default

## QA Runs Performed

Compile verification:

- `python3 -m py_compile ISRC_manager.py isrc_manager/history/cleanup.py isrc_manager/history/manager.py isrc_manager/storage_admin.py isrc_manager/ui_common.py isrc_manager/storage_sizes.py isrc_manager/app_dialogs.py isrc_manager/history/dialogs.py isrc_manager/services/settings_reads.py isrc_manager/services/settings_mutations.py`

Focused storage/history/settings/UI run:

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_history_cleanup_service tests.test_storage_admin_service tests.test_settings_read_service tests.test_settings_mutations_service tests.test_settings_transfer_service tests.test_storage_sizes tests.test_ui_common tests.test_theme_builder tests.app.test_app_shell_startup_core`

Broader regression sweep:

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_history_budget_hooks tests.test_app_dialogs tests.test_history_dialogs tests.app.test_app_shell_profiles_and_selection tests.test_theme_builder tests.test_ui_common tests.test_storage_admin_service tests.test_history_cleanup_service`

Final spot-check after wording updates:

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_history_dialogs tests.test_app_dialogs tests.test_history_cleanup_service tests.test_storage_admin_service tests.test_ui_common tests.test_storage_sizes`

## Tests Added Or Updated

Added:

- `tests/test_storage_sizes.py`

Updated:

- hard-cap retention behavior at `keep_latest=1`
- hard-cap retention behavior at `keep_latest=5`
- visible-undo overflow retention reporting
- in-place quarantine of old snapshot-create entries
- admin cleanup expectations for quarantined history entries
- orphan snapshot/backup companion discovery in Storage Admin
- settings read/write max-budget behavior
- settings bundle round-trip for `1 TB`
- unit-aware budget spinbox formatting/parsing
- accelerated step behavior and reset behavior
- preset/custom synchronization when storage budget changes
- app-shell projected-growth routing to `Application Storage Admin`

## Known Edge Cases And Follow-Up Risks

- `HistoryCleanupDialog.inspect()` still reports protected snapshot references conservatively for general inspection. That is acceptable because hard-cap retention enforcement now has its own authoritative visible-undo-based pruning logic, but future UX work could align preview language even more tightly with retention results.
- The effective retained live-snapshot count can exceed the configured cap only when the current visible undo boundary itself needs more live snapshots than the cap. This is intentional and reported in the retention result.
- Diagnostics still exposes `History Cleanup` as an explicit tool. That is intentional, but over-budget resolution should continue to route to `Application Storage Admin`.
- If downstream code ever needs literal “deleted dependent history entry ids” from storage-admin cleanup results, that contract has changed and should be renamed in a future cleanup pass.

## Final Product Statement

The repo now treats snapshot retention and storage-budget policy as real contracts instead of best-effort hints:

- retained snapshot count is authoritative for live snapshots
- cleanup removes stale rows and stale files together
- the current visible undo boundary remains protected
- budget values are exact internally and readable in the UI
- over-budget users are sent to the app-wide storage-management surface that can actually inspect and delete the relevant storage

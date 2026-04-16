# Catalog Refresh Blob-Badge Performance And Visibility Follow-Up

## Summary

This handoff documents the follow-up work that landed after [`truthful-post-save-background-orchestration-for-works-tracks-and-albums.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/truthful-post-save-background-orchestration-for-works-tracks-and-albums.md).

The earlier post-save/background-loader pass fixed the worst save/delete hangs and kept the loader open through the final UI-ready step. After that work, one real bottleneck still remained:

- catalog refresh was still doing per-row blob/media metadata lookups on the UI thread while rebuilding the table

During the first attempt to optimize that path, a short-lived regression was introduced where the catalog table could appear blank because table updates were still suspended during the final repaint flush.

This follow-up fixes both issues:

1. blob/media badge metadata is now prepared in the background catalog dataset load
2. the main-thread apply path now uses that prepared payload instead of querying live metadata row by row
3. catalog view updates are re-enabled before the final repaint flush so the table is visible when control returns

## Why This Changed

The remaining sluggishness after track add/delete was not fake or cosmetic. The loader stayed open longer, but `_apply_blob_badges(...)` still called live metadata services once per visible row:

- `track_media_meta(...)`
- `cf_get_value_meta(...)`

Those service calls were happening on the main thread while the table was already being rebuilt, so the UI could still feel frozen or jittery during the late catalog refresh phase even though icon generation itself had been cached.

The first optimization pass moved repaint ownership later in the loader, but that alone was not enough because:

- the expensive part was still metadata collection, not only painting
- the first table-update suspension scope accidentally covered the final repaint flush

## Files / Layers Affected

### Runtime

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/services/catalog_reads.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/catalog_reads.py)
- [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py)
- [`isrc_manager/services/custom_fields.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/custom_fields.py)

### Tests

- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [`tests/app/test_app_shell_editor_surfaces.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_editor_surfaces.py)

## Root Cause

### Remaining UI-thread bottleneck

`App._apply_blob_badges(...)` walked the already-populated catalog table and, for each row:

- queried standard media metadata through `TrackService.get_media_meta(...)`
- queried custom blob metadata through `CustomFieldValueService.get_value_meta(...)`

That meant add/delete/save flows were still paying for:

- row-by-row metadata lookups
- album/shared-art resolution
- custom-field blob metadata reads

on the UI thread during the final table refresh.

### Visibility regression from the first optimization pass

To reduce redraw churn, the first follow-up introduced a temporary catalog-view update suspension while the refreshed table state was being applied.

The bug was:

- the suspension scope still wrapped the final repaint flush
- child widget update states were being captured after a parent widget had already been disabled

So the viewport/header update state could be restored incorrectly and the flush could run while updates were still disabled, leaving the table visually blank even though the data existed.

## Implementation

## 1. Prepared badge metadata is now part of the background catalog dataset

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py), `_load_catalog_ui_dataset(...)` now includes a `blob_badges` payload alongside:

- `active_custom_fields`
- `rows`
- `cf_map`
- `combo_values`

That payload is loaded from the worker-side bundle path as part of the real catalog refresh work, not synthesized later on the UI thread.

The loader/progress copy was also updated from:

- `Loading refreshed catalog rows and lookup values...`

to:

- `Loading refreshed catalog rows, media badges, and lookup values...`

because badge metadata preparation is now part of the truthful worker milestone.

## 2. Catalog read services now batch blob/media metadata

### Standard media

In [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py), `TrackService.get_media_meta_map(...)` was added to bulk-resolve:

- `audio_file`
- `album_art`

for a set of track ids.

It preserves the existing album-art semantics:

- direct track art
- shared album art
- album-track fallback art

but computes those results in batch on the worker connection instead of one row at a time on the UI thread.

### Custom blob fields

In [`isrc_manager/services/custom_fields.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/custom_fields.py), `CustomFieldValueService.get_value_meta_map(...)` was added to bulk-resolve custom blob metadata for:

- a set of field ids
- optionally scoped to a set of track ids

This returns the same metadata shape the UI already expects, including storage-mode details.

### Read-only catalog bundling

In [`isrc_manager/services/catalog_reads.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/catalog_reads.py), `CatalogReadService.fetch_blob_badge_payload(...)` now coordinates:

- bulk standard-media metadata loading
- bulk custom-field blob metadata loading

so the catalog dataset arrives with a ready-to-apply badge payload.

## 3. Main-thread badge application now consumes prepared payload first

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py), `_apply_blob_badges(...)` now accepts `prepared_payload=...`.

Behavior is now:

- use prepared standard/custom badge metadata when present
- fall back to live `track_media_meta(...)` / `cf_get_value_meta(...)` only for older synchronous callers that do not provide prepared payloads

This preserves compatibility for legacy refresh paths while removing the per-row live-query bottleneck from the post-save/delete catalog refresh flows.

## 4. Catalog repaint suspension was narrowed and corrected

In [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py), `_apply_catalog_refresh_request(...)` now:

- suspends catalog view updates only during the table/header/state application phase
- re-enables those updates before `_flush_pending_catalog_repaints(...)`

In the same file, `_suspend_catalog_view_updates()` was corrected so it:

- captures all widget `updatesEnabled()` states before disabling any of them
- restores the original states accurately afterward

This fixes the blank-table regression from the first version of the optimization.

## Threading / Boundary Model

### Off-thread now

- catalog rows with custom values
- standard media badge metadata
- custom blob badge metadata
- lookup/combo value payloads

### Main-thread only

- table/header widget mutation
- icon assignment to items
- tooltip/text assignment
- view-state restoration
- selection restoration
- final repaint drain

This keeps widget access on the main thread while moving the expensive safe reads into the worker bundle.

## Truthful Progress Semantics

This follow-up keeps the earlier loader contract intact.

The loader still only reaches `100%` after:

- background mutation is done
- refreshed rows are loaded
- refreshed badge metadata is loaded
- lookup values are loaded
- the table is applied on the main thread
- add-track/history dependent state is refreshed
- the final repaint flush finishes with updates enabled

No fake progress stages were added. The badge-preparation work is now represented by real worker-side milestones.

## QC Checks Performed

- confirmed the remaining slow path was still live per-row badge metadata work on the UI thread
- confirmed icon caching alone was not sufficient because metadata collection remained synchronous
- confirmed prepared badge payload is now built in the background catalog load path
- confirmed the main-thread badge pass uses prepared payload before any live fallback
- confirmed the repaint flush runs after catalog updates are re-enabled
- confirmed the viewport/header update-state restore bug was fixed
- confirmed post-save/delete truthful progress behavior still reaches `100%` only after the final UI-ready phase

## QA / Validation Performed

### Compile

- `python3 -m py_compile ISRC_manager.py isrc_manager/services/catalog_reads.py isrc_manager/services/tracks.py isrc_manager/services/custom_fields.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py`

### Focused regressions

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_catalog_refresh_uses_prepared_blob_badges_without_live_meta_queries`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_catalog_refresh_reenables_table_updates_before_final_repaint_flush`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_blob_badge_icon_generation_is_cached_during_refresh`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_add_track_save_progress_reaches_100_only_after_final_ui_refresh`
- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_profiles_and_selection.AppShellProfileAndSelectionTests.test_track_delete_progress_reaches_100_only_after_final_ui_refresh`

### Broader app-shell rerun

- `env QT_QPA_PLATFORM=offscreen python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_profiles_and_selection tests.app.test_app_shell_workspace_docks`

## Tests Added

In [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py):

- `case_catalog_refresh_uses_prepared_blob_badges_without_live_meta_queries`
  - verifies the catalog dataset contains prepared badge payload
  - verifies `_apply_catalog_ui_dataset(...)` does not fall back to live per-row metadata lookups when that payload exists

- `case_catalog_refresh_reenables_table_updates_before_final_repaint_flush`
  - verifies the catalog table, viewport, and headers have updates enabled before the final repaint flush runs
  - guards against the blank-table regression

Wired through [`tests/app/test_app_shell_editor_surfaces.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_editor_surfaces.py).

## Relationship To Previous Handoffs

This patch is a direct follow-up to:

- [`truthful-post-save-background-orchestration-for-works-tracks-and-albums.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/truthful-post-save-background-orchestration-for-works-tracks-and-albums.md)

It does not replace that handoff. It narrows the remaining hot path inside the catalog-refresh apply cycle and fixes a regression introduced during that optimization.

It also continues the same design direction as:

- [`open-database-ui-thread-bottleneck-followup.md`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/open-database-ui-thread-bottleneck-followup.md)

The architectural rule is still the same:

- load heavy read-only data in the background bundle
- apply widgets on the main thread
- keep the loader open until the UI is actually ready

## Residual Risks / Follow-Ups

- Older synchronous callers that invoke `_apply_blob_badges(...)` directly without a prepared dataset still use the live fallback path. They are compatible, but they do not benefit from the full batching improvement until they are routed through the prepared dataset path.
- Very large tables can still spend noticeable time on main-thread item/icon application because widget mutation itself is not thread-safe. The improvement here is that metadata lookup is no longer adding to that same UI-thread cost.
- The icon-generation cache and prepared badge payload are complementary. If future changes touch badge theming or blob-icon settings again, both cache invalidation and prepared-payload usage should be kept aligned.

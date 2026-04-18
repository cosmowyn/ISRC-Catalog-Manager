# B4 Handoff - Badge/Icon And Proxy-Semantic Parity

## Phase Scope Confirmation

- Phase executed: B4 only.
- Engineering plan was read before implementation.
- B4 goal from the plan: ensure icon, tooltip, media export, and audio-preview order behavior reads through model roles and proxy ordering only.
- No worker agents were used. There were no idle workers to close.
- No B5 zoom work, final cleanup/removal, broad UI redesign, or unrelated refactor was performed.

## What Changed

- Badge icons now flow through the catalog model instead of being recreated by the compatibility item wrapper.
- `CatalogCellValue` can carry a prepared decoration payload, and `CatalogTableModel.data(..., Qt.DecorationRole)` returns that payload when present.
- The live catalog snapshot builder now resolves the cached badge `QIcon` while preparing media/blob cell values, alongside the existing tooltip, raw payload, display text, and search text.
- The `CatalogTableView.item(...).icon()` compatibility helper now reads the model `DecorationRole` directly and no longer hashes tooltip/text into a placeholder icon.
- `CatalogTableController` gained model-role helpers for column-key lookup and proxy-visible index iteration.
- Context-menu media behavior now resolves clicked cells through `CatalogTableController.cell_target(...)`, `ColumnKeyRole`, `TrackIdRole`, `RawValueRole`, and proxy-visible order.
- Audio-preview navigation now walks proxy-visible media-column indexes and filters playable rows by model `RawValueRole`.
- Focused media export now normalizes selected track IDs into current proxy order before dispatching export work.
- Standard/custom media export specs now carry stable `column_key` metadata, so later export steps can resolve model columns without relying on display header text.

## Files Added

- `docs/change control/Change - QTableWidget/phase execution handoffs/B4 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `isrc_manager/catalog_table/controller.py`
- `isrc_manager/catalog_table/models.py`
- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/main_window_shell.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_catalog_model_view.py`
- `docs/change control/Milestones.md`

## Existing Files Touched And Why

- `ISRC_manager.py`: bounded live cutover for B4 media/icon/context/export/audio-preview paths, plus phase-appropriate deprecation markers for replaced monolith responsibilities.
- `isrc_manager/catalog_table/models.py`: added a decoration payload slot to the existing cell value object so prepared icons can travel with the snapshot.
- `isrc_manager/catalog_table/table_model.py`: exposed the prepared icon through `Qt.DecorationRole`.
- `isrc_manager/catalog_table/controller.py`: added column-key and visible-index helpers, and made cell targeting prefer stable model column keys before legacy header/position fallback.
- `isrc_manager/main_window_shell.py`: removed the temporary compatibility icon shim so item compatibility reads the actual model role.
- `tests/app/_app_shell_support.py` and `tests/app/test_app_shell_catalog_model_view.py`: added B4 validation coverage for icon caching, no render-path metadata lookup, audio preview proxy order, media export proxy order, and proxy/source role mapping.

## Live Behavior Cut Over In B4

- Badge/icon rendering for catalog media/blob cells is now model-role backed.
- Tooltips for media/blob cells remain snapshot/model-role backed.
- Audio-preview navigation uses proxy-visible order and model raw media roles.
- Focused media export orders track IDs by proxy-visible order.
- Context-menu media detection for standard/custom media cells uses controller cell targeting and model raw payload roles before legacy fallback.

## Live Behavior Not Cut Over

- Zoom was not implemented or wired.
- Final cleanup/removal of deprecated monolith helpers was not performed.
- Legacy compatibility helpers were not deleted.
- Header-state, selection, refresh, search, and shell migration behavior beyond the B4 parity pass was not widened.
- Storage conversion execution internals were not redesigned; only their selected-track order input was aligned with proxy order where B4 required it.

## Deprecation Markers Added

- `_track_id_for_table_row`
- `_row_for_id`
- `_column_index_by_header`
- `_set_blob_indicator`
- `_get_row_pk`
- `_apply_blob_badges`

These markers follow the existing `CATALOG_TABLE_CUTOVER_DEPRECATED` convention and do not emit runtime warnings.

## Dormant Imports, Wrappers, Or Seams

- No dormant imports were added.
- No new user-facing wrappers were added.
- Existing transitional compatibility wrappers remain in place because final cleanup is a later phase.
- New seams are limited to B4 model/proxy helpers:
  - `CatalogTableController.column_for_key(...)`
  - `CatalogTableController.visible_indexes(...)`
  - `CatalogCellValue.decoration`

## QA Checks Performed

- `python3 -m py_compile ISRC_manager.py isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/controller.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m unittest tests.app.test_app_shell_catalog_model_view`
- `python3 -m unittest tests.app.test_app_shell_catalog_controller`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_authenticity_table_context_menu_exposes_export_actions tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_standard_media_context_menu_groups_file_and_storage_actions tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_custom_blob_context_menu_groups_file_and_storage_actions tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_audio_preview_navigation_follows_visible_catalog_order_and_auto_advance`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_standard_audio_badge_uses_distinct_icons_for_managed_and_database_storage tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_standard_album_art_badge_uses_distinct_icons_for_managed_and_database_storage tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_custom_blob_image_badge_uses_distinct_icons_for_managed_and_database_storage tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_blob_badge_icon_generation_is_cached_during_refresh tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_catalog_refresh_uses_prepared_blob_badges_without_live_meta_queries`
- `python3 -m black isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/controller.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m py_compile ISRC_manager.py`
- `python3 -m ruff check isrc_manager/catalog_table/models.py isrc_manager/catalog_table/table_model.py isrc_manager/catalog_table/controller.py isrc_manager/main_window_shell.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_model_view.py`
- `git diff --check`
- `make compile`

## B4 Validation Coverage

- Badge icon caching still works: covered by model-role icon cache tests and existing storage-mode badge icon tests.
- No live metadata lookups in render path: covered by a render-path test that patches `track_media_meta` and `cf_get_value_meta` to fail if called while reading item icon/tooltip.
- Audio preview navigation matches visible proxy order: covered by B4 proxy-order navigation test and existing auto-advance order test.
- Proxy/source mapping remains correct under sort+filter+selection: covered by a B4 test that filters, sorts, selects, maps proxy indexes back to source, and verifies `RawValueRole`.

## QC Checks Performed

- Confirmed the engineering plan was read and B4 scope was isolated.
- Reviewed changed files against the B4 allowed file/behavior list.
- Confirmed no zoom cutover, final cleanup/removal, or adjacent B5/B6 work was implemented.
- Confirmed no worker agents were used, so worker scope could not widen.
- Confirmed deprecated monolith functions were marked only where responsibilities are now live on the model/controller role path.

## Risks And Follow-Up Notes

- Some deprecated monolith helpers still exist intentionally for compatibility and final cleanup. They should not be removed until the cleanup phase.
- Context menus still call service metadata for storage-conversion availability, which is outside render-path badge/icon lookup and remained intentionally unchanged.
- `ISRC_manager.py` is excluded from Black/Ruff by project configuration, so formatting inside that file remains manual.
- App-shell tests use shared `case_*` methods in `tests/app/_app_shell_support.py` and expose them through thin test modules; future phase tests should follow that convention.

## Exceptions

- None.

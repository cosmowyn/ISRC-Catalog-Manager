# B6 Handoff - Final Catalog Table Cleanup

## Phase Scope Confirmation

- Phase executed: B6 only.
- Engineering plan was read before implementation.
- B6 goal from the plan: remove deprecated catalog-table cutover helpers, stale `QTableWidget` compatibility paths, obsolete wrappers, dead imports, and update docs/help for the final model/view catalog table path.
- No worker agents were used. There were no idle workers to close.
- No new catalog behavior, new cutover work, data refresh redesign, zoom behavior change, or future-phase work was performed.

## What Changed

- Removed the transitional `CatalogTableView` compatibility adapter and its shim cell/header item classes.
- Instantiated the live catalog table as a plain `QTableView`.
- Updated catalog search, double-click, and context-menu signal wiring to the model/view-native handlers.
- Removed deprecated monolith wrappers and helpers that only existed for the old widget table path.
- Replaced remaining production call sites with direct `CatalogTableController`, model, proxy, and header-data access.
- Removed controller widget-seam binding and fallback logic now that the live path is model/view-only.
- Migrated catalog table tests away from widget item/range helpers and onto model/view helpers.
- Updated catalog workspace docs and in-app help copy to describe the model-backed visible-row behavior and zoom persistence.

## Files Added

- `docs/change control/Change - QTableWidget/phase execution handoffs/B6 handoff.md`

## Files Modified

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_table/controller.py`
- `isrc_manager/help_content.py`
- `docs/catalog-workspace-workflows.md`
- `tests/test_catalog_table_controller.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_catalog_header_state.py`
- `docs/change control/Milestones.md`

## Existing Files Touched And Why

- `ISRC_manager.py`: removed deprecated catalog table wrappers/classes, renamed live model/view handlers to explicit catalog names, switched old wrapper call sites to controller/model access, and removed stale badge/widget no-op paths.
- `isrc_manager/main_window_shell.py`: removed the catalog `QTableView` compatibility subclass and connected shell signals directly to live model/view handlers.
- `isrc_manager/catalog_table/controller.py`: removed widget seam binding and widget fallback lookups while keeping controller APIs for selection, identity, visible IDs, and cell targeting.
- `isrc_manager/help_content.py`: refreshed help text to describe model-backed visible rows and persisted zoom.
- `docs/catalog-workspace-workflows.md`: documented model-backed filtering/visible-row behavior and zoom density persistence.
- `tests/test_catalog_table_controller.py`: rebuilt controller coverage around a real `QTableView`, `CatalogTableModel`, and `CatalogFilterProxyModel`.
- `tests/app/_app_shell_support.py`: replaced catalog widget-item assumptions with model/view helper methods and controller-based assertions.
- `tests/app/test_app_shell_catalog_header_state.py`: read headers through model header data instead of widget header items.

## Cleanup Performed

- Removed all code-scoped `CATALOG_TABLE_CUTOVER_DEPRECATED` functions/classes that B6 was responsible for.
- Removed obsolete helpers including the old search wrapper, table item factory, widget population path, selected/visible/default ID wrappers, row/header lookup wrappers, context-menu wrappers, double-click wrapper, row primary-key wrapper, and blob-badge widget wrapper.
- Removed the catalog widget compatibility adapter methods: `rowCount`, `columnCount`, `item`, `horizontalHeaderItem`, `currentRow`, `setCurrentCell`, `sortItems`, and `scrollToItem`.
- Removed the controller `bind_widget_seams(...)` API and its fallback row-hidden/track-id logic.
- Removed stale catalog-table imports introduced only for compatibility shims.

## Live Behavior Not Changed

- No catalog data model behavior was redesigned.
- No search semantics were intentionally changed beyond removing the obsolete wrapper layer.
- No zoom behavior was changed.
- No table refresh pipeline behavior was intentionally changed.
- Non-catalog `QTableWidget` uses remain in separate dialogs/panes and were intentionally out of B6 scope.

## QA Checks Performed

- `python3 -m unittest tests.test_catalog_table_controller tests.test_catalog_table_models tests.test_catalog_table_header_zoom`
- `python3 -m unittest tests.app.test_app_shell_catalog_model_view tests.app.test_app_shell_catalog_header_state`
- `python3 -m unittest tests.app.test_app_shell_layout_persistence tests.app.test_app_shell_startup_core`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces.AppShellEditorSurfaceTests.test_bulk_audio_column_export_uses_background_task_and_embeds_catalog_metadata`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks tests.app.test_app_shell_editor_surfaces`
- `python3 -m black isrc_manager/main_window_shell.py isrc_manager/catalog_table/controller.py isrc_manager/help_content.py tests/test_catalog_table_controller.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_header_state.py tests/app/test_app_shell_catalog_model_view.py`
- `python3 -m ruff check isrc_manager/main_window_shell.py isrc_manager/catalog_table/controller.py isrc_manager/help_content.py tests/test_catalog_table_controller.py tests/app/_app_shell_support.py tests/app/test_app_shell_catalog_header_state.py tests/app/test_app_shell_catalog_model_view.py`
- `make compile`
- `git diff --check`

## Dead-Code Review

- `rg` found no code/test/doc hits for `CATALOG_TABLE_CUTOVER_DEPRECATED` in the B6-scoped catalog paths.
- `rg` found no B6-scoped hits for removed transitional names such as `CatalogTableView`, `_CatalogTable*`, `bind_widget_seams`, `_apply_catalog_ui_dataset`, `apply_search_filter`, `_row_for_id`, `_column_index_by_header`, `_on_item_double_clicked`, `_on_table_context_menu`, or `_apply_blob_badges`.
- `rg` found no catalog app-shell test use of old widget helpers such as `self.window.table.item(...)`, `setCurrentCell`, `sortItems`, `horizontalHeaderItem`, or the removed private wrapper methods.
- Remaining `QTableWidget` references are outside the main catalog table workspace path and belong to non-catalog or separate catalog-management dialog tables.

## Risks And Follow-Up Notes

- `ISRC_manager.py` remains excluded from Black/Ruff by project configuration, so formatting there remains manual.
- Historical prompt and handoff documents still mention deprecated names as historical records; the code path no longer carries them.
- Because B6 intentionally avoided behavior changes, any future polish should treat further catalog manager dialog `QTableWidget` cleanup as a separate scoped change.

## Exceptions

- None.

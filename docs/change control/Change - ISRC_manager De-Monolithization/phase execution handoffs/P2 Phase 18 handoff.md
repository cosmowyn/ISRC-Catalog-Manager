# Plan 2 Phase 18 Handoff - Catalog Workflow Controller

Completion timestamp: 2026-05-24 23:01:06 CEST

Status: Completed

## Source Documents Read
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-18 - Catalog Workflow Controller.md`

## Files Added
- `isrc_manager/isrc_registry_controller.py`
- `isrc_manager/catalog_table/workflow.py`
- `isrc_manager/catalog_table/context_menu.py`
- `isrc_manager/catalog_table/media_routing.py`
- `isrc_manager/custom_fields/__init__.py`
- `isrc_manager/custom_fields/controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 18 handoff.md`

## Files Modified
- `ISRC_manager.py`
- `pyproject.toml`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed
- Moved catalog table dataset refresh, model snapshot application, search/filter, count/duration, combo lookup loading, catalog repaint flushing, and view-state preservation orchestration into `isrc_manager.catalog_table.workflow`.
- Moved catalog context-menu construction and catalog cell blob preview routing into `isrc_manager.catalog_table.context_menu`.
- Moved catalog media/blob routing helpers, drag/drop media routing, standard track media helpers, storage-mode prompting, and attach/delete/preview standard media workflows into `isrc_manager.catalog_table.media_routing`.
- Moved custom-field definition management and catalog custom-cell editing orchestration into `isrc_manager.custom_fields.controller`.
- Moved application-wide ISRC registry sync/conflict/reservation/generation/prefix orchestration into `isrc_manager.isrc_registry_controller`.
- Replaced the moved `App` methods with thin delegation shims.
- Added `isrc_manager.custom_fields` to the explicit package list in `pyproject.toml`.

## Why It Changed
Phase 18 required catalog workflow responsibilities to leave `ISRC_manager.py` while preserving catalog behavior through delegation. The extraction builds on the existing `CatalogTableController`; selection, proxy mapping, and cell-target authority remain there.

## Scope Control
- Scope stayed limited to Plan 2 Phase 18 catalog workflow, custom-field workflow, catalog media/blob routing, and ISRC registry/generation orchestration.
- No Phase 19 feature-family workflow controllers were created.
- Media player, waveform cache orchestration, equalizer, bookmarks, audio export, conversion, authenticity, quality, update, promo-code, contract, rights, asset, and party workflow controller work was not implemented.
- Existing Plan 1 media preview dialogs remain in their media UI modules; preview dialogs were not pulled into Phase 18 controller modules.

## Intentionally Not Implemented
- No final `App` move.
- No final root compatibility cleanup.
- No CI gate implementation.
- No broad UI redesign.
- No Phase 19A-I feature workflow extraction.
- No new catalog selection authority beyond the existing `CatalogTableController`.

## QA Checks
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/isrc_registry_controller.py isrc_manager/catalog_table/workflow.py isrc_manager/catalog_table/context_menu.py isrc_manager/catalog_table/media_routing.py isrc_manager/custom_fields`
- `.venv/bin/python -m ruff check isrc_manager/isrc_registry_controller.py isrc_manager/catalog_table/workflow.py isrc_manager/catalog_table/context_menu.py isrc_manager/catalog_table/media_routing.py isrc_manager/custom_fields/controller.py`
- Import smoke for:
  - `isrc_manager.isrc_registry_controller`
  - `isrc_manager.catalog_table.workflow`
  - `isrc_manager.catalog_table.context_menu`
  - `isrc_manager.catalog_table.media_routing`
  - `isrc_manager.custom_fields.controller`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_catalog_table_models.py tests/test_catalog_table_controller.py tests/test_catalog_workflow_integration.py tests/test_custom_field_services.py tests/test_isrc_registry.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_catalog_model_view.py tests/app/test_app_shell_catalog_controller.py tests/app/test_app_shell_catalog_header_state.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py -k 'catalog or custom or isrc or media or blob'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_profiles_and_selection.py -k 'catalog or filter or combobox or profile_switch'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'catalog or media or edit_menu'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -k 'catalog'`

## QC Checks
- Confirmed the engineering plan, mandatory enforcement plan, and Phase 18 prompt were read before implementation.
- Confirmed extracted modules do not import `ISRC_manager.py`.
- Confirmed `CatalogTableController` remains the selection/proxy/cell-target authority.
- Confirmed `pyproject.toml` package parity is valid at 27 pyproject packages and 27 filesystem packages.
- Confirmed static import-cycle count remains 3 and did not increase.
- Confirmed no compatibility alias was added, removed, migrated, or changed.
- Confirmed no adjacent Phase 19+ workflow controller was implemented.

## Compatibility Inventory Change Status
Unchanged. No aliases were added, changed, migrated, or removed during Phase 18. Active alias count remains 42.

## Root Alias Additions/Removals
None.

## Deprecated Wrapper Additions/Removals
None. The new `App` delegating methods are temporary phase shims but are not root compatibility aliases.

## Dormant Imports, Wrappers, Seams, Aliases, or Deprecation Markers
- Added thin `App` delegation shims for moved methods.
- Added no new deprecated root wrappers or compatibility aliases.
- Preserved root-module patchability for existing app-shell tests by resolving patched root objects for context menus, dialogs, storage-mode prompts, message boxes, and snapshot-history helper calls where the moved workflows still rely on test monkeypatch seams.

## Architecture Boundary Observations
- `catalog_table.workflow` owns dataset/search/count/duration/view-state orchestration.
- `catalog_table.context_menu` owns context-menu construction only.
- `catalog_table.media_routing` owns catalog media/blob routing and standard-media attach/delete/preview helpers; it does not own media playback, equalizer, waveform cache orchestration, bookmarks, or export controller responsibilities.
- `custom_fields.controller` owns catalog custom-field management/editing orchestration and reuses existing custom-field services.
- `isrc_registry_controller` owns application-wide ISRC registry/generation orchestration and reuses `ApplicationISRCRegistryService`.

## Package Parity Impact
Changed and valid. `isrc_manager.custom_fields` was added to the explicit package list. Package parity is 27/27.

## Import-Cycle Risk Observations
Low. New modules depend on focused package modules and do not import `ISRC_manager.py`. Static import-cycle count remains at the baseline of 3:
- `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
- `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
- `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`

## Module-Size / Mini-Monolith Risk Observations
- `isrc_manager.catalog_table.workflow.py` is 1,142 LOC, below but close to the 1,200 LOC warning threshold.
- `isrc_manager.catalog_table.context_menu.py` is 463 LOC.
- `isrc_manager.catalog_table.media_routing.py` is 566 LOC.
- `isrc_manager.custom_fields.controller.py` is 436 LOC.
- `isrc_manager.isrc_registry_controller.py` is 359 LOC.
- The extraction avoided creating a single catalog mega-controller, but `workflow.py` should stay watched during later catalog-adjacent changes.

## Architecture Metrics Impact
Recorded in `architecture_metrics.md`:
- `ISRC_manager.py` LOC: 18,846
- `App` LOC: 18,080
- compatibility alias count: 42 active entries
- root import count: 8 Python test imports; 0 package imports
- module LOC over warning threshold: 35
- module LOC over mandatory split threshold: 11
- import cycle count: 3
- package parity status: valid at 27/27

## Permanent Migration Glue Check
No permanent migration glue was created. The remaining `App` methods are temporary delegation shims to preserve runtime behavior while later Plan 2 phases continue reducing `App`.

## New Compatibility Alias Policy Check
No new compatibility alias was added. No inventory entry was required.

## Repo-Specific Conventions Discovered
- Existing app-shell tests patch root `ISRC_manager` dialog/menu/helper objects even after implementation code moves. Extracted workflows that invoke these objects should resolve patched root objects until Phase 21 removes root compatibility seams.
- `CatalogTableController` is the established authority for selected track ids, proxy/source mapping, visible indexes, and context-menu cell targets.
- New packages must be listed explicitly in `pyproject.toml`; adding `isrc_manager.custom_fields` was required for package parity.

## Risks / Follow-Up Notes For Next Phase
- `catalog_table.workflow.py` is close to the warning threshold. Later phases should avoid adding unrelated behavior to it.
- The root app-shell test import dependency remains unchanged and must be cleared before Phase 21.
- Phase 19A should start with release/work workflow extraction only and must not pull catalog workflow logic back into feature-family controllers.

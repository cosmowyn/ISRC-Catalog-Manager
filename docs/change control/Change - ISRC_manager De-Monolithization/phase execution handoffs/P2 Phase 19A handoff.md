# Plan 2 Phase 19A Handoff - Releases and Works Workflow Controllers

Completion timestamp: 2026-05-24 23:15:27 CEST

Status: Completed

## Source Documents Read
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`

## Selected Subphase
Phase 19A - Releases and Works Workflow Controllers.

The Phase 19 prompt requires exactly one named subphase per Codex run unless a later planning document authorizes combining them. This handoff covers Phase 19A only.

## Files Added
- `isrc_manager/releases/controller.py`
- `isrc_manager/works/controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19A handoff.md`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed
- Moved Release Browser creation, opening, release choice/context helpers, release create/update, release-from-selection, add-to-release, browser refresh, delete, and duplicate orchestration into `isrc_manager.releases.controller`.
- Moved Work Manager panel creation/configuration/opening, governed-track context helpers, work choice/context helpers, create/update/duplicate/link/delete orchestration, and work-scoped child-track/album entry routes into `isrc_manager.works.controller`.
- Replaced the moved `App` methods with thin delegation shims.
- Preserved existing root-module patchability for message boxes, editor/browser panels, and snapshot-history helper calls where app-shell tests still patch through `ISRC_manager`.

## Why It Changed
Phase 19A required releases and works workflow orchestration to leave `ISRC_manager.App` while keeping the feature services and dialogs as the domain/UI owners. The extraction reduces `App` surface area without changing release/work runtime behavior.

## Scope Control
- Scope stayed limited to Plan 2 Phase 19A releases and works workflows.
- No Phase 19B-I controller work was implemented.
- No media controller, conversion, authenticity, provenance, quality, update, promo-code, contract, rights, asset, party, or exchange workflow controller work was implemented.
- No final `App` move, root compatibility cleanup, or Phase 20/Phase 21 work was implemented.
- The release and work controllers did not absorb catalog-table selection authority; they continue to ask existing App/catalog-table seams for selected track ids and catalog refresh behavior.

## Intentionally Not Implemented
- No combined Phase 19 subphase execution.
- No new catch-all feature controller.
- No new compatibility aliases or deprecated root wrappers.
- No CI gate implementation.
- No package-list change; `isrc_manager.releases` and `isrc_manager.works` already existed as packages.

## QA Checks
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/releases/controller.py isrc_manager/works/controller.py`
- `.venv/bin/python -m ruff check isrc_manager/releases/controller.py isrc_manager/works/controller.py`
- Import smoke for:
  - `isrc_manager.releases.controller`
  - `isrc_manager.works.controller`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_release_service.py tests/test_work_and_party_services.py tests/test_repertoire_dialogs.py tests/test_catalog_workflow_integration.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_profiles_and_selection.py -k 'work or release or add_track' tests/app/test_app_shell_editor_surfaces.py -k 'work or release or add_track'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py::AppShellWorkspaceDockTests::test_work_manager_dock_uses_live_track_selection`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -k 'release_browser or work_manager or create_work or work_delete or relationship_search_work or quality_governance_issue'`

## QC Checks
- Confirmed the engineering plan, mandatory enforcement plan, and Phase 19 prompt were read before implementation.
- Confirmed only Phase 19A was executed from the Phase 19 prompt.
- Confirmed extracted modules do not import `ISRC_manager.py`.
- Confirmed package parity remains valid at 27 pyproject packages and 27 filesystem packages.
- Confirmed static import-cycle count remains 3 and did not increase.
- Confirmed no compatibility alias was added, removed, migrated, or changed.
- Confirmed the release/work extraction did not create a media/controller/settings catch-all module.

## Compatibility Inventory Change Status
Unchanged. No aliases were added, changed, migrated, or removed during Phase 19A. Active alias count remains 42.

## Root Alias Additions/Removals
None.

## Deprecated Wrapper Additions/Removals
None. The new `App` delegating methods are temporary phase shims but are not root compatibility aliases.

## Dormant Imports, Wrappers, Seams, Aliases, or Deprecation Markers
- Added thin `App` delegation shims for moved release/work methods.
- Added no new deprecated root wrappers or compatibility aliases.
- Preserved root-module patchability for existing app-shell tests by resolving patched root objects for message boxes, editor dialogs, browser panels, and snapshot-history helper calls where the moved workflows still rely on test monkeypatch seams.

## Architecture Boundary Observations
- `isrc_manager.releases.controller` owns release workflow orchestration only; release persistence remains in `ReleaseService` and release UI remains in the release dialogs/panels.
- `isrc_manager.works.controller` owns work workflow orchestration only; work persistence remains in `WorkService` and work UI remains in the work dialogs/panels.
- The controllers reuse existing catalog refresh, selected-track, history, audit, and background-task seams instead of becoming new catalog or task authorities.
- Phase 19A did not move media playback, waveform cache, equalizer, bookmark, export, conversion, authenticity, provenance, quality, update, promo-code, contract, rights, asset, or party responsibilities.

## Package Parity Impact
Unchanged and valid. `isrc_manager.releases` and `isrc_manager.works` were already listed in `pyproject.toml`; package parity remains 27/27.

## Import-Cycle Risk Observations
Low. New modules depend on focused feature/service modules and do not import `ISRC_manager.py`. Static import-cycle count remains at the baseline of 3:
- `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
- `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
- `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`

## Module-Size / Mini-Monolith Risk Observations
- `isrc_manager.releases.controller.py` is 864 LOC.
- `isrc_manager.works.controller.py` is 1,042 LOC.
- Both new controllers are below the 1,200 LOC warning threshold.
- Phase 19A avoided creating a shared feature mega-controller and did not combine other Phase 19 subphases.

## Architecture Metrics Impact
Recorded in `architecture_metrics.md`:
- `ISRC_manager.py` LOC: 17,204
- `App` LOC: 16,436
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
- Existing app-shell tests patch root `ISRC_manager` dialog/helper objects even after implementation code moves. Extracted workflows that invoke those objects should resolve patched root objects until Phase 21 removes root compatibility seams.
- Synchronous work mutations that previously used `App._run_snapshot_history_action` must continue using that App wrapper. The lower-level task helper requires an explicit history manager and is intended for bundle/background contexts.
- Phase 19 subphases should remain one feature family per run unless a later planning document explicitly authorizes a combined run.

## Risks / Follow-Up Notes For Next Phase
- The root app-shell test import dependency remains unchanged and must be cleared before Phase 21.
- `isrc_manager.works.controller.py` is below the warning threshold but already substantial; later work subphase changes should not add unrelated responsibilities to it.
- Phase 19B should proceed next and must not pull release/work workflow logic back into catalog or exchange controllers.

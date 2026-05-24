# Plan 2 Phase 19B Handoff - Exchange, Master Transfer, Import, and Export Controllers

Completion timestamp: 2026-05-24 23:27:36 CEST

Status: Completed

## Source Documents Read
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`

## Selected Subphase
Phase 19B - Exchange, Master Transfer, Import, and Export Controllers.

The Phase 19 prompt requires exactly one named subphase per Codex run unless a later planning document authorizes combining them. This handoff covers Phase 19B only.

## Files Added
- `isrc_manager/exchange/controller.py`
- `isrc_manager/exchange/master_transfer_controller.py`
- `isrc_manager/exchange/repertoire_controller.py`
- `isrc_manager/exchange/repair_queue_controller.py`
- `isrc_manager/exchange/catalog_xml_controller.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/P2 Phase 19B handoff.md`

## Files Modified
- `ISRC_manager.py`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## What Changed
- Moved core catalog exchange import/export orchestration into `isrc_manager.exchange.controller`.
- Moved master transfer preview/export/import/review/report orchestration into `isrc_manager.exchange.master_transfer_controller`.
- Moved Contracts and Rights repertoire exchange import/export orchestration into `isrc_manager.exchange.repertoire_controller`.
- Moved track import repair queue listing, repair, deletion, and dialog-opening orchestration into `isrc_manager.exchange.repair_queue_controller`.
- Moved catalog XML full/selected export and XML import routing into `isrc_manager.exchange.catalog_xml_controller`.
- Replaced the moved `App` methods with thin delegation shims.
- Preserved existing root-module patchability for file dialogs, message boxes, import/review dialogs, master transfer preview dialog, and history helper calls where app-shell tests still patch through `ISRC_manager`.

## Why It Changed
Phase 19B required exchange, master transfer, import, and export workflow orchestration to leave `ISRC_manager.App` while keeping existing exchange services, XML services, dialogs, and history helpers as the feature owners.

## Scope Control
- Scope stayed limited to Plan 2 Phase 19B core exchange, master transfer, repertoire exchange, import repair queue, and catalog XML import/export workflows.
- Party exchange stayed in `App` for Phase 19I party-controller work.
- Tag/audio metadata import/export stayed in `App` for Phase 19C/19D/19E.
- Promo-code import stayed in `App` for Phase 19H.
- Contract template import/export stayed in `App` for Phase 19I.
- No final `App` move, root compatibility cleanup, or Phase 20/Phase 21 work was implemented.

## Intentionally Not Implemented
- No combined Phase 19 subphase execution.
- No new catch-all import/export controller that absorbs party, media, authenticity, promo-code, or contract-template workflows.
- No compatibility alias or deprecated root-wrapper changes.
- No CI gate implementation.
- No package-list change; `isrc_manager.exchange` already existed as a package.

## QA Checks
- `.venv/bin/python -m compileall -q ISRC_manager.py isrc_manager/exchange/controller.py isrc_manager/exchange/master_transfer_controller.py isrc_manager/exchange/repertoire_controller.py isrc_manager/exchange/repair_queue_controller.py isrc_manager/exchange/catalog_xml_controller.py`
- `.venv/bin/python -m ruff check isrc_manager/exchange/controller.py isrc_manager/exchange/master_transfer_controller.py isrc_manager/exchange/repertoire_controller.py isrc_manager/exchange/repair_queue_controller.py isrc_manager/exchange/catalog_xml_controller.py`
- Import smoke for:
  - `isrc_manager.exchange.controller`
  - `isrc_manager.exchange.master_transfer_controller`
  - `isrc_manager.exchange.repertoire_controller`
  - `isrc_manager.exchange.repair_queue_controller`
  - `isrc_manager.exchange.catalog_xml_controller`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py -k 'master_transfer or repertoire or catalog_import or exchange' tests/app/test_app_shell_startup_core.py -k 'master_transfer'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_editor_surfaces.py -k 'repertoire_export or master_transfer or catalog_import or repertoire_import'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_workspace_docks.py -k 'repertoire_export or repertoire_csv_bundle or catalog_import or repertoire_import'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/app/test_app_shell_startup_core.py -k 'xml_import or exchange_exports or master_transfer'`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/exchange tests/test_exchange_dialogs.py tests/test_xml_export_service.py tests/test_xml_import_service.py`
- `git diff --check`

## QC Checks
- Confirmed the engineering plan, mandatory enforcement plan, and Phase 19 prompt were read before implementation.
- Confirmed only Phase 19B was executed from the Phase 19 prompt.
- Confirmed extracted modules do not import `ISRC_manager.py`.
- Confirmed package parity remains valid at 27 pyproject packages and 27 filesystem packages.
- Confirmed static import-cycle count remains 3 and did not increase.
- Confirmed no compatibility alias was added, removed, migrated, or changed.
- Confirmed party, tag/metadata, media/audio, authenticity/provenance, quality, update, promo-code, contract, rights, asset, and party controller work was not implemented.

## Compatibility Inventory Change Status
Unchanged. No aliases were added, changed, migrated, or removed during Phase 19B. Active alias count remains 42.

## Root Alias Additions/Removals
None.

## Deprecated Wrapper Additions/Removals
None. The new `App` delegating methods are temporary phase shims but are not root compatibility aliases.

## Dormant Imports, Wrappers, Seams, Aliases, or Deprecation Markers
- Added thin `App` delegation shims for moved exchange/master transfer/repertoire/import repair/XML methods.
- Added no new deprecated root wrappers or compatibility aliases.
- Preserved root-module patchability for existing app-shell tests by resolving patched root objects for file dialogs, message boxes, import/review dialogs, master transfer export preview dialog, and history helper calls where moved workflows still rely on test monkeypatch seams.

## Architecture Boundary Observations
- `exchange.controller` owns catalog exchange import/export orchestration only; exchange parsing/persistence remains in `ExchangeService`.
- `exchange.master_transfer_controller` owns master transfer UI orchestration only; package inspection/export/import remains in `MasterTransferService`.
- `exchange.repertoire_controller` owns Contracts and Rights repertoire exchange UI orchestration only; data logic remains in `RepertoireExchangeService`.
- `exchange.repair_queue_controller` owns import repair queue UI orchestration only; repair queue storage remains in `TrackImportRepairQueueService`.
- `exchange.catalog_xml_controller` owns catalog XML workflow routing only; XML read/write logic remains in `XMLImportService` and `XMLExportService`.
- The extraction avoided moving party exchange, media export, audio metadata import, promo-code import, and contract-template workflows into Phase 19B.

## Package Parity Impact
Unchanged and valid. `isrc_manager.exchange` was already listed in `pyproject.toml`; package parity remains 27/27.

## Import-Cycle Risk Observations
Low. New modules depend on focused exchange/service/dialog modules and do not import `ISRC_manager.py`. Static import-cycle count remains at the baseline of 3:
- `isrc_manager.media.waveform_cache` <-> `isrc_manager.services.tracks`
- `isrc_manager.contract_templates.html_support` <-> `isrc_manager.contract_templates.ingestion`
- `isrc_manager.tags.catalog` <-> `isrc_manager.tags.service`

## Module-Size / Mini-Monolith Risk Observations
- `isrc_manager.exchange.controller.py` is 695 LOC.
- `isrc_manager.exchange.master_transfer_controller.py` is 598 LOC.
- `isrc_manager.exchange.repertoire_controller.py` is 380 LOC.
- `isrc_manager.exchange.repair_queue_controller.py` is 219 LOC.
- `isrc_manager.exchange.catalog_xml_controller.py` is 187 LOC.
- All new Phase 19B modules are below the 1,200 LOC warning threshold.
- The extraction intentionally split exchange sub-responsibilities rather than creating one import/export mega-controller.

## Architecture Metrics Impact
Recorded in `architecture_metrics.md`:
- `ISRC_manager.py` LOC: 15,370
- `App` LOC: 14,597
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
- Directory-backed exports, such as repertoire CSV bundles, must use snapshot history instead of file history.
- Write-mode imports run a dry-run review before applying changes; this review gate is part of the app workflow and must remain intact across later controller moves.

## Risks / Follow-Up Notes For Next Phase
- The root app-shell test import dependency remains unchanged and must be cleared before Phase 21.
- Party exchange remains intentionally in `App` for Phase 19I; later phases should not duplicate its import/review helper logic.
- Phase 19C should proceed next and must stay limited to tags and metadata workflows.

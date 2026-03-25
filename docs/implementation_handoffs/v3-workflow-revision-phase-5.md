# V3 Workflow Revision Phase 5

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 5 is planned and not started.

This placeholder handoff was created during Phase 0 so the final legacy-removal and shell-alignment pass has a reserved continuation path.

## Phase Goal

Remove obsolete legacy-license logic and align the application shell to the final v3 product shape.

## What Changed

None yet.

This file was created during Phase 0 to reserve the handoff path and record the intended scope boundary.

## Source Of Truth Files And Surfaces

Expected initial Phase 5 surfaces:

- `isrc_manager/quality/service.py`
- `isrc_manager/exchange/service.py`
- `isrc_manager/services/schema.py`
- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- legacy license service and migration surfaces still present at that time
- app-shell and integration test modules covering menus, actions, and exports

## Files Changed

None yet.

## Tests Added Or Updated

None yet.

Expected early test focus:

- no direct reads from `Licensees`, `Licenses`, or `vw_Licenses`
- shell/menu/context cleanup coverage
- final export, quality, and search regressions

## What Was Intentionally Deferred

- no additional major feature work should be introduced here beyond clearly documented follow-up fixes

## Risks And Caveats

- Phase 5 should only remove legacy surfaces after authoritative replacement pathways are already stable
- if old database compatibility is dropped here, the break should be documented honestly in the handoff and release notes

## Workers Used And Workers Closed

None yet.

Workers should be recorded here when Phase 5 actually starts.

## QA/QC Summary From Central Oversight

Phase 0 central-oversight instruction:

- the final app should feel like one intentional product and should not continue advertising obsolete license workflows

## Exact Safe Pickup Instructions

Before starting Phase 5:

1. read the masterplan and the completed Phase 4 handoff
2. confirm all replacement data paths are already in production code
3. identify every remaining license-specific runtime and shell surface
4. remove the obsolete paths and update tests in the same phase
5. document any deliberate compatibility break honestly

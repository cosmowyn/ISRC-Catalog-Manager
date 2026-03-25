# V3 Workflow Revision Phase 4

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 4 is planned and not started.

This placeholder handoff was created during Phase 0 so the Catalog integration cleanup has a reserved continuation path.

## Phase Goal

Keep `Catalog` strong as the operational inventory while reducing duplicated governance and identity logic.

## What Changed

None yet.

This file was created during Phase 0 to reserve the handoff path and record the intended scope boundary.

## Source Of Truth Files And Surfaces

Expected initial Phase 4 surfaces:

- `isrc_manager/catalog_workspace.py`
- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/quality/service.py`
- `isrc_manager/exchange/service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/integration/test_global_search_relationships.py`

## Files Changed

None yet.

## Tests Added Or Updated

None yet.

Expected early test focus:

- catalog read projections from authoritative work and Party data
- bulk-edit and track-edit operational behavior
- search and quality integration after governance-model cleanup
- exchange/export integration against the new authoritative sources

## What Was Intentionally Deferred

- final legacy license deletion
- final shell cleanup

## Risks And Caveats

- Phase 4 must not recreate a second governance surface inside Catalog while cleaning up operational views
- catalog changes should consume the Phase 2 and Phase 3 model instead of inventing transitional duplicate fields

## Workers Used And Workers Closed

None yet.

Workers should be recorded here when Phase 4 actually starts.

## QA/QC Summary From Central Oversight

Phase 0 central-oversight instruction:

- Catalog stays the operational inventory and execution layer, not the primary product-creation concept

## Exact Safe Pickup Instructions

Before starting Phase 4:

1. read the masterplan and the completed Phase 3 handoff
2. confirm the work-context creation flow is stable
3. identify catalog reads and actions that still depend on old governance or identity duplication
4. add integration tests before broad workspace cleanup
5. keep final legacy-license deletion out of this phase unless the replacement pathways are already complete

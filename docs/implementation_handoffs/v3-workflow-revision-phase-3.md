# V3 Workflow Revision Phase 3

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 3 is planned and not started.

This placeholder handoff was created during Phase 0 so the Work Manager and creation-workflow rewrite has a reserved continuation path.

## Phase Goal

Make `Work Manager` the primary creation and governance surface for parent works and child tracks.

## What Changed

None yet.

This file was created during Phase 0 to reserve the handoff path and record the intended scope boundary.

## Source Of Truth Files And Surfaces

Expected initial Phase 3 surfaces:

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/works/*`
- `isrc_manager/services/tracks.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/app/_app_shell_support.py`

## Files Changed

None yet.

## Tests Added Or Updated

None yet.

Expected early test focus:

- create work plus first-track flow
- add child-track flows from work context
- Work Manager tab and action coverage
- work-linked issue routing from quality/search surfaces

## What Was Intentionally Deferred

- catalog operational cleanup
- final legacy license deletion

## Risks And Caveats

- Phase 3 must not leave both floating-track creation and work-context creation as equally prominent default paths
- work seeding into first-track creation should not silently overwrite later work metadata

## Workers Used And Workers Closed

None yet.

Workers should be recorded here when Phase 3 actually starts.

## QA/QC Summary From Central Oversight

Phase 0 central-oversight instruction:

- treat `Add Track` as a work-context child creation flow, not as the conceptual first stop for governed products

## Exact Safe Pickup Instructions

Before starting Phase 3:

1. read the masterplan and the completed Phase 2 handoff
2. confirm the parent-child domain model is stable enough for UI work
3. define the smallest coherent Work Manager rewrite slice
4. add workflow tests before shell and dialog expansion
5. keep Catalog in operational scope rather than turning it into a second governance entry point

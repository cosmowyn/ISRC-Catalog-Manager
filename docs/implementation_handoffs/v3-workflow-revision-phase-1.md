# V3 Workflow Revision Phase 1

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 1 is planned and not started.

This placeholder handoff was created during Phase 0 so the next implementation pass has a reserved pickup path.

## Phase Goal

Make identity-bearing workflow paths Party-first across the targeted v3 governance surfaces.

## What Changed

None yet.

This file was created during Phase 0 to reserve the handoff path and record the intended scope boundary.

## Source Of Truth Files And Surfaces

Expected initial Phase 1 surfaces:

- `isrc_manager/parties/*`
- `isrc_manager/works/*`
- `isrc_manager/contracts/*`
- `isrc_manager/rights/*`
- `isrc_manager/services/schema.py`
- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`

## Files Changed

None yet.

## Tests Added Or Updated

None yet.

Expected early test focus:

- Party selector behavior
- quick-create Party flows
- owner identity resolution
- work and contract binding behavior

## What Was Intentionally Deferred

- work-parent and track-child schema revision
- creation workflow rewrite
- catalog projection cleanup
- legacy license removal

## Risks And Caveats

- free-text identity debt currently exists in multiple surfaces, so Phase 1 must stay bounded and sequence the cutover carefully
- Phase 1 should not accidentally introduce a second parallel identity model while converting fields to Party-first behavior

## Workers Used And Workers Closed

None yet.

Workers should be recorded here when Phase 1 actually starts.

## QA/QC Summary From Central Oversight

Phase 0 central-oversight instruction:

- do Party authority first so later governance-model work does not multiply identity debt

## Exact Safe Pickup Instructions

Before starting Phase 1:

1. read the v3 masterplan
2. read the Phase 0 handoff
3. inspect live identity-bearing fields and selectors
4. define the smallest bounded Party-first slice
5. add tests before broad UI expansion

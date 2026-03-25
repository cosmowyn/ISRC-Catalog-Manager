# V3 Workflow Revision Phase 2

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 2 is ready to start.

Phase 1 is now completed, so Phase 2 is the active next implementation phase.

No runtime Phase 2 changes have landed yet in this handoff. This document now serves as the direct pickup point for the domain-model revision.

## Phase Goal

Revise the domain model toward a parent `Work`, child `Track`, and explicitly separated ownership and contribution architecture.

## What Changed

No runtime changes yet.

This handoff now reflects the post-Phase-1 starting boundary for the schema and service revision.

## Source Of Truth Files And Surfaces

Expected initial Phase 2 surfaces:

- `isrc_manager/services/schema.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/works/*`
- `isrc_manager/rights/*`
- `tests/database/*`
- `tests/test_work_and_party_services.py`
- `tests/test_catalog_workflow_integration.py`

## Files Changed

None yet.

## Tests Added Or Updated

None yet.

Expected early test focus:

- schema current-target coverage
- work-parent and track-child linkage
- ownership and contribution table coverage
- Party-first identity invariants on the new relations

## What Was Intentionally Deferred

- Work Manager UI expansion
- creation workflow rewrite
- catalog operational cleanup
- legacy license deletion

## Risks And Caveats

- Phase 2 is the first phase allowed to break older database compatibility deliberately
- governance-model cleanup must avoid keeping `WorkTrackLinks` as an accidental long-term authority if the cleaner v3 model replaces it

## Workers Used And Workers Closed

None yet.

Workers should be recorded here when Phase 2 implementation begins.

## QA/QC Summary From Central Oversight

Central-oversight instruction for the Phase 2 kickoff:

- separate work ownership, recording ownership, and contribution roles explicitly instead of hiding them behind generic rights rows
- treat the completed Phase 1 Party cutover as a prerequisite that is now satisfied
- keep the first Phase 2 landing at the schema/service layer; do not mix in Work Manager expansion or track-creation UX yet

## Exact Safe Pickup Instructions

When starting Phase 2:

1. read the masterplan and the completed Phase 1 handoff
2. confirm the Party authority cutover needed by this model is in place
3. define the new parent-child and ownership tables or equivalents
4. add schema and service tests before UI changes
5. keep catalog cleanup out of this phase

# V3 Workflow Revision Planning Wave 1 Checkpoint

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status

Planning Wave 1 is reconciled and closed.

This checkpoint captures the first planning-wave conclusions that were handed forward into the v3 master strategy.

## Purpose

Planning Wave 1 existed to inspect the current repository and answer the first six architectural questions before the later phasing and continuity pass began.

Wave 1 focused on:

- current workflow audit
- work/track domain model
- ownership and rights layering
- Party integration
- Catalog and Work UI restructuring
- legacy removal and schema cleanup

## Worker Scopes

The six Wave 1 scopes were:

1. current workflow audit
2. work and track domain model
3. ownership and rights layering
4. Party integration
5. Catalog and Work UI restructuring
6. legacy removal and schema cleanup

These scopes were reconciled under central oversight before any Wave 2 planning work proceeded.

## Reconciled Findings

### Workflow audit

- the live app is still track-first by default
- `Work Manager` exists and should be strengthened, not removed
- `Catalog` is highly important but is currently too close to being a conceptual entry point instead of staying the operational inventory

### Work and track model

- work-level and track-level metadata are still mixed today, especially where composition-adjacent fields live on `Tracks`
- the intended v3 shape is a stronger parent `Work` with governed child `Track` records
- later versions, remixes, and alternate masters should be modeled as child-track relationships inside the parent work context

### Ownership and rights layering

- current concepts are too collapsed to represent composition ownership, master ownership, and contribution ledgers cleanly
- v3 needs explicit separation between:
  - work ownership
  - recording or master ownership
  - contributions and roles

### Party integration

- `Party` already exists but is not yet the default identity authority across all identity-bearing surfaces
- later phases should replace free-text-first identity storage with Party selectors plus quick-create flows wherever practical

### Catalog and Work UI restructuring

- `Work Manager` should become the main governance surface
- `Catalog` should stay strong for search, filtering, bulk operations, and operational execution
- floating track creation should stop being the default UX

### Legacy removal and schema cleanup

- legacy license logic is still present in runtime code and tests
- backward compatibility with older databases is not the controlling priority for this revision
- obsolete license surfaces should be removed deliberately in a later cleanup phase instead of being preserved indefinitely

## Constraints For Wave 2

Wave 2 needed to answer the remaining planning questions without reopening Wave 1 scope:

- define the phase order and acceptance boundaries
- define the structural and workflow validation strategy
- define pause-safe continuity and handoff rules
- preserve the 6-worker cap by closing idle Wave 1 workers before starting the next planning scopes

## Workers Closed

All Wave 1 worker scopes were closed after reconciliation.

This checkpoint exists so later phases do not need to restage the first planning wave just to recover the architectural baseline.

## Safe Handoff To Wave 2

Wave 2 should proceed by:

1. using this checkpoint as the fixed architectural baseline
2. defining phase order, dependencies, and acceptance boundaries
3. defining the test strategy and continuity model
4. writing the masterplan and Phase 0 handoff on the final v3 paths
5. closing any remaining idle workers once their findings are integrated

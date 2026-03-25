# V3 Album Governance Decision Note

Date: 2026-03-25

Status: `reconciled / active guardrail`

## Purpose

Freeze the current album-governance shape before Phase 4 broadens catalog cleanup.

This note defines:

- which album creation modes are allowed in v3 right now
- which mode is the intended default product behavior
- what remains explicitly deferred so later work does not accidentally broaden the album model

## Album Dialog Role

The album dialog remains a `release / batch-entry` surface.

It is not a parent-governance authoring surface.

That means:

- `Work Manager` remains the primary parent-governance entry point
- the album dialog may bind a batch to one existing parent work
- the album dialog may auto-create governed parent works in fallback mode
- the album dialog must not grow its own separate album-level governance model

## Allowed Album Creation Modes

### 1. Shared Parent Work Batch

Allowed when the whole album batch belongs under one governing `Work`.

Expected behavior:

- user launches `Add Album to Work` from `Work Manager`, or selects one parent work in the album dialog
- every created `Track` receives that shared `work_id`
- every created `Track` receives the chosen shared `relationship_type`
- no orphaned child tracks are left behind

This is the preferred governed mode when one composition-level parent work is genuinely correct for the whole batch.

### 2. Auto-Governed Per-Track Work Batch

Allowed as the fallback when the user does not choose a shared parent work.

Expected behavior:

- user opens album entry without selecting a parent work
- on save, the app creates one parent `Work` per saved `Track`
- each new `Track` is linked immediately to its new parent `Work`
- each created child track lands as `relationship_type = original`
- the batch does not invent an album-level governance parent or any third governance layer

This mode is allowed so grouped recording entry does not create floating orphan tracks, but it is not the preferred conceptual path when one existing parent work is already known.

## Default Behavior

The default intended v3 behavior is:

- if the album batch belongs to one known governing work, creation should start from `Work Manager` and remain locked to that selected parent work
- if the user does not choose a shared parent work, the system may still save the batch, but it must auto-govern it by creating one work per track instead of leaving unmanaged tracks behind

Product interpretation:

- default conceptual path: `Work Manager -> Add Album to Work`
- allowed operational fallback: album entry without a selected work, with automatic per-track work creation
- disallowed normal path: saving a new album batch that leaves created tracks ungoverned

## Mixed-Mode Rule

No album batch save may silently mix governance modes.

For one save operation, the batch must resolve as exactly one of these:

- `shared-parent mode`: every saved track attaches to the same selected parent `Work`
- `auto-governed fallback mode`: every saved track gets its own newly created parent `Work`

This is explicitly disallowed:

- one save where some tracks attach to a selected shared parent work while other tracks auto-create new parents
- one save where different tracks silently attach to different pre-existing parent works
- any implicit fallback that changes only part of the batch after the user started in another governance mode

## Explicitly Deferred

The following are not defined for this pass and must not be broadened implicitly during Phase 4:

- one album save that assigns different tracks to different pre-existing parent works
- per-track work pickers inside the album dialog
- mixed batches where some tracks attach to an existing shared work and others auto-create new works in the same save
- richer auto-created work authoring beyond title and ISWC seeding
- special multi-work compilation semantics, medley semantics, or suite semantics
- any rule that makes `Catalog` the primary place to design album governance
- any album-level governance entity that sits above or beside the existing `Work` parent model

## Guardrail For Next Work

Before further Phase 4 implementation:

1. read this note together with [`v3-workflow-revision-phase-3.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-phase-3.md)
2. treat the two allowed modes above as the only approved album-governance modes for now
3. do not turn the album dialog into a parent-governance authoring surface while refining batch entry
4. if later work needs multi-work album behavior, stop and write a new decision note first instead of widening the runtime model ad hoc

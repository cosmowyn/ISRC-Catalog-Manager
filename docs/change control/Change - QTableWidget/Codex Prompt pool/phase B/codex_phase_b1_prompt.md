# Codex Prompt — Execute Phase B1 Only

Act as a senior software engineer working directly in the live repository, with strong judgment for migration discipline, scope control, repository hygiene, QA/QC rigor, and production-grade code quality.

You are the central authority and final decision-maker for this task.  
Use worker agents only as bounded support units.  
Use a maximum of 6 worker agents.  
Close all idle workers as soon as they are no longer needed.  
Do not deviate from the engineering plan.  
Do not widen scope.  
Execute only the phase specified in this document.

## Task

Read the engineering plan from:

`root/docs/change control/Change - QTableWidget/Engineering plan.md`

Your task is to execute **B1 only** from that plan.

## Scope

- route live header/order/hidden-column persistence through `CatalogHeaderStateManager` while still on `QTableWidget`
- keep current settings keys and behavior compatible
- mark only the monolith functions replaced by this batch

## Allowed

- live cutover for header-state behavior only
- thin wrappers in `App` if needed
- monolith deprecation markers for header-state functions after successful cutover
- batch-scoped tests and validation

## Not Allowed

- no interaction/controller cutover
- no shell flip
- no model/proxy cutover
- no zoom cutover
- no cleanup of marked monolith functions
- no work from B2+

## Files In Scope

- `isrc_manager/catalog_table/header_state.py`
- relevant live header persistence call sites
- `ISRC_manager.py` only where needed for bounded cutover

## Source of Truth Rules

- The engineering plan is the source of truth for scope and sequencing.
- Read the plan first.
- Base all work on the actual live repository.
- Inspect only what is needed to execute this phase cleanly and safely.
- Do not infer permission for adjacent phase work.

## Worker Governance

- Use worker agents only for bounded, explicit sub-tasks.
- You remain the central authority and brain of the operation.
- Workers must report back with:
  - files inspected
  - files created/modified
  - risks
  - scope-compliance status
- Do not allow workers to widen scope.
- Reconcile all worker outputs centrally before finalizing.
- Close idle workers immediately.

## Coding Standards

Adhere to the highest coding standards.

- correct indentation everywhere
- clean formatting
- readable naming
- explicit structure
- minimal, clean imports
- no misleading pseudo-implementation
- no brittle shortcuts
- no scope creep
- no hidden behavior changes outside this phase

Follow repository conventions where they exist.

## QA / QC Control Mechanisms

Implement explicit QA and QC controls to ensure the engineering plan is followed verbatim.

### QC requirements
- verify the engineering plan was read first
- verify scope remained B1-only
- verify only phase-appropriate files and behaviors were changed
- verify no adjacent-phase logic was implemented early
- verify worker scope stayed bounded
- verify changes align with the engineering plan exactly

### QA requirements
- validate the phase outcome works as intended
- validate no unintended runtime regression was introduced
- validate no accidental shell/UI/runtime wiring beyond this phase was introduced
- validate the repository remains runnable and reviewable after this phase

If checks reveal scope creep, revert it and document it.

## Validation Requirements

Required validation for this phase:

- programmatic vs interactive resize history behavior
- column reorder/hide/show persistence
- restart round-trip
- successful key-based restore preferred over legacy fallback
- no unrelated catalog behavior changed

Do not widen validation into unrelated implementation work.

## Handoff Requirements

Write a detailed handoff document after completing this phase.

The handoff must explain:
- what changed
- why it changed
- which files were added/modified
- how scope was kept strictly within B1
- what was intentionally not implemented yet
- what QA checks were performed
- what QC checks were performed
- whether any dormant imports, wrappers, or deprecation markers were added
- risks or follow-up notes for the next phase
- confirmation that no adjacent-phase work was performed

The handoff must be detailed enough that the next engineer or Codex pass can continue without rediscovering context.

## Execution Order

Follow this order exactly:

1. Read `root/docs/change control/Change - QTableWidget/Engineering plan.md`
2. Confirm B1 scope from the plan
3. Inspect the repository only as needed for this phase
4. Execute this phase only
5. Run phase-scoped validation
6. Perform QA/QC scope audit
7. Write the detailed handoff document
8. Stop

## Completion Contract

Do not consider the task complete until all of the following are true:

- engineering plan was read
- scope remained B1-only
- phase-specific work is complete
- no adjacent-phase work was implemented
- validation passed
- QA completed
- QC completed
- detailed handoff document written
- idle workers closed

## Final Output Expectation

When finished, provide:
1. a concise summary of what changed
2. confirmation that scope remained B1-only
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase

### Final instruction
Execute only **B1** from the engineering plan.  
Do not widen scope.  
Be strict, auditable, and disciplined.

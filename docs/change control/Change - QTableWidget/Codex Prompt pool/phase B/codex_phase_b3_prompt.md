# Codex Prompt — Execute Phase B3 Only

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

Your task is to execute **B3 only** from that plan.

## Scope

- replace the live Catalog widget with `QTableView`
- bind `CatalogTableModel` and `CatalogFilterProxyModel`
- move refresh/filter/sort/count/duration behavior to the new path
- keep scope strictly to the shell flip and model/proxy live path

## Allowed

- live shell flip to `QTableView`
- signal rewiring
- refresh/filter/sort/count/duration cutover
- monolith deprecation markers for replaced item-widget population/sort/filter helpers
- split into B3a/B3b internally if needed, but do not drift into B4+

## Not Allowed

- no badge/icon parity work beyond what is required for the shell to function
- no zoom cutover
- no final cleanup/removal
- no broad unrelated refactors
- no B4/B5/B6 work

## Files In Scope

- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/catalog_table/filter_proxy.py`
- bounded live call sites in `ISRC_manager.py`

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
- verify scope remained B3-only
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

- full catalog view loads
- search/filter/count/duration correct
- selection and view-state restore correct
- truthful progress unchanged
- visible-row semantics now based on proxy-visible rows only

Do not widen validation into unrelated implementation work.

## Handoff Requirements

Write a detailed handoff document after completing this phase.

The handoff must explain:
- what changed
- why it changed
- which files were added/modified
- how scope was kept strictly within B3
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
2. Confirm B3 scope from the plan
3. Inspect the repository only as needed for this phase
4. Execute this phase only
5. Run phase-scoped validation
6. Perform QA/QC scope audit
7. Write the detailed handoff document
8. Stop

## Completion Contract

Do not consider the task complete until all of the following are true:

- engineering plan was read
- scope remained B3-only
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
2. confirmation that scope remained B3-only
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase

### Final instruction
Execute only **B3** from the engineering plan.  
Do not widen scope.  
Be strict, auditable, and disciplined.

# Codex Prompt — Execute Phase B6 Only

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

Your task is to execute **B6 only** from that plan.

## Scope

- remove all functions marked `CATALOG_TABLE_CUTOVER_DEPRECATED`
- remove dead imports, obsolete wrappers, and stale catalog `QTableWidget` paths
- perform final cleanup only after the new path is stable

## Allowed

- deletion of marked redundant monolith logic
- dead import cleanup
- obsolete wrapper cleanup
- docs/help updates required by final cleanup
- final broad regression validation

## Not Allowed

- no new behavior work
- no new cutover work
- no widening scope beyond marked cleanup and directly required cleanup fallout

## Files In Scope

- `ISRC_manager.py` marked redundant functions
- stale catalog widget paths
- dead imports and obsolete wrappers
- relevant docs/help files

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
- verify scope remained B6-only
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

- broad regression rerun
- dead-code review
- docs/help updated
- no marked redundant catalog logic remains in the monolith

Do not widen validation into unrelated implementation work.

## Handoff Requirements

Write a detailed handoff document after completing B6.

### Handoff output location
Write the handoff document to:

`root/docs/change control/Change - QTableWidget/phase execution handoffs/`

If the folder does not exist yet, create it.

### Handoff file naming rule
Name the handoff file exactly:

`B6 handoff.md`

Do not use any other file name.  
Do not merge this handoff with any other phase handoff.  
Do not place the handoff anywhere else unless the task explicitly says otherwise.

The handoff must explain:
- what changed
- why it changed
- which files were added
- which files were modified
- whether any existing files were touched and why
- how scope was kept strictly within B6
- what was intentionally not implemented yet
- what QA checks were performed
- what QC checks were performed
- whether any dormant imports, wrappers, seams, or deprecation markers were added or removed
- confirmation that no adjacent-phase work was performed
- confirmation of exactly which cleanup behavior was performed in this phase
- confirmation that no non-B6 behavior work or cutover work was introduced
- risks or follow-up notes after final cleanup
- any repo-specific conventions discovered that matter for future maintenance

The handoff must be detailed enough that the next engineer or Codex pass can continue without rediscovering context.

## Execution Order

Follow this order exactly:

1. Read `root/docs/change control/Change - QTableWidget/Engineering plan.md`
2. Confirm B6 scope from the plan
3. Inspect the repository only as needed for this phase
4. Execute this phase only
5. Run phase-scoped validation
6. Perform QA/QC scope audit
7. Write the detailed handoff document
8. Update `root/docs/change control/Milestones.md`
9. Stop

## Completion Contract

Do not consider the task complete until all of the following are true:

- engineering plan was read
- scope remained B6-only
- phase-specific work is complete
- no adjacent-phase work was implemented
- validation passed
- QA completed
- QC completed
- detailed handoff document written
- milestone written to `Milestones.md`
- idle workers closed

## Milestone Update Requirement

On completion of this prompt, update the document:

`root/docs/change control/Milestones.md`

### Update rules
- Append the new milestone entry after any existing milestone entries already in the document.
- Do not overwrite, reorder, or reformat previous milestone entries.
- If the file does not exist yet, create it.

### Milestone entry content
For the completed phase, record:
- the phase identifier
- a completion timestamp
- a short completion status
- whether any exceptions occurred

Use a clear append-only entry format, for example:

- `B6 — completed — 18-apr-2026 14:32`
- `Exceptions: none`

or, if exceptions occurred:

- `B6 — completed with exceptions — 18-apr-2026 14:32`
- `Exceptions: B6.1, B6.2`

### Exceptions section
Also maintain an `Exceptions` section in the same document.

Rules:
- create the `Exceptions` section if it does not yet exist
- append new exceptions after any existing exceptions
- do not renumber old exceptions
- each exception must use a phase-based reference with a follow number, for example:
  - `B6.1`
  - `B6.2`

For each exception, record:
- the exception reference
- the phase
- a short description of what happened
- whether it was resolved in the current phase or remains open

Example:

- `B6.1 — Phase B6 — one deprecated helper was retained temporarily because removal would break an unrelated startup path discovered during regression validation — open`
- `B6.2 — Phase B6 — one dead import cleanup required a small docs path correction — resolved`

### Scope discipline
- Only record the phase that was actually executed by the current prompt.
- Do not mark future phases as complete.
- Do not rewrite milestone history beyond appending the new completed phase entry and any new exceptions.

## Final Output Expectation

When finished, provide:
1. a concise summary of what changed
2. confirmation that scope remained B6-only
3. QA/QC summary
4. the handoff document path
5. any follow-up notes after final cleanup
6. confirmation that the milestone was written to `Milestones.md`

### Final instruction
Execute only **B6** from the engineering plan.  
Do not widen scope.  
Be strict, auditable, and disciplined.
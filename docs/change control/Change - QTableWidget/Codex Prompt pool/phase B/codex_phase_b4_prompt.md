# Codex Prompt — Execute Phase B4 Only

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

Your task is to execute **B4 only** from that plan.

## Scope

- ensure icon, tooltip, media export, and audio-preview order behavior reads through model roles and proxy ordering only
- complete badge/icon and proxy-semantic parity
- mark only the monolith functions replaced by this batch

## Allowed

- live parity adjustments using model roles and proxy ordering
- monolith deprecation markers for replaced identity/item-text helpers
- batch-scoped tests and validation

## Not Allowed

- no zoom cutover
- no final cleanup/removal
- no unrelated refactors
- no broader UI redesign
- no B5/B6 work

## Files In Scope

- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/catalog_table/controller.py`
- relevant live media/export/audio paths
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
- verify scope remained B4-only
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

- badge icon caching still works
- no live metadata lookups in render path
- audio preview navigation matches visible proxy order
- proxy/source mapping remains correct under sort+filter+selection

Do not widen validation into unrelated implementation work.

## Handoff Requirements

Write a detailed handoff document after completing B4.

### Handoff output location
Write the handoff document to:

`root/docs/change control/Change - QTableWidget/phase execution handoffs/`

If the folder does not exist yet, create it.

### Handoff file naming rule
Name the handoff file exactly:

`B4 handoff.md`

Do not use any other file name.  
Do not merge this handoff with any other phase handoff.  
Do not place the handoff anywhere else unless the task explicitly says otherwise.

The handoff must explain:
- what changed
- why it changed
- which files were added
- which files were modified
- whether any existing files were touched and why
- how scope was kept strictly within B4
- what was intentionally not implemented yet
- what QA checks were performed
- what QC checks were performed
- whether any dormant imports, wrappers, seams, or deprecation markers were added
- confirmation that no adjacent-phase work was performed
- confirmation of exactly which live behavior was cut over in this phase
- confirmation that no non-B4 live behavior was cut over
- risks or follow-up notes for the next phase
- any repo-specific conventions discovered that matter for later phases

The handoff must be detailed enough that the next engineer or Codex pass can continue without rediscovering context.

## Execution Order

Follow this order exactly:

1. Read `root/docs/change control/Change - QTableWidget/Engineering plan.md`
2. Confirm B4 scope from the plan
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
- scope remained B4-only
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

- `B4 — completed — 18-apr-2026 14:32`
- `Exceptions: none`

or, if exceptions occurred:

- `B4 — completed with exceptions — 18-apr-2026 14:32`
- `Exceptions: B4.1, B4.2`

### Exceptions section
Also maintain an `Exceptions` section in the same document.

Rules:
- create the `Exceptions` section if it does not yet exist
- append new exceptions after any existing exceptions
- do not renumber old exceptions
- each exception must use a phase-based reference with a follow number, for example:
  - `B4.1`
  - `B4.2`
  - `B5.1`

For each exception, record:
- the exception reference
- the phase
- a short description of what happened
- whether it was resolved in the current phase or remains open

Example:

- `B4.1 — Phase B4 — one tooltip/media parity path needed a temporary compatibility wrapper during cutover — resolved`
- `B4.2 — Phase B4 — one non-blocking icon-size parity issue identified during validation and deferred to B5 because it depends on zoom behavior — open`

### Scope discipline
- Only record the phase that was actually executed by the current prompt.
- Do not mark future phases as complete.
- Do not rewrite milestone history beyond appending the new completed phase entry and any new exceptions.

## Final Output Expectation

When finished, provide:
1. a concise summary of what changed
2. confirmation that scope remained B4-only
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase
6. confirmation that the milestone was written to `Milestones.md`

### Final instruction
Execute only **B4** from the engineering plan.  
Do not widen scope.  
Be strict, auditable, and disciplined.
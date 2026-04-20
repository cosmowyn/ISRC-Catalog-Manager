# Codex Prompt — Execute Phase 12 Only

Act as a senior software engineer working directly in the live repository, with strong judgment for migration discipline, scope control, repository hygiene, QA/QC rigor, token-budget discipline, and production-grade code quality.

You are the central authority and final decision-maker for this task.
Use worker agents only as bounded support units.
Use a maximum of 6 worker agents.
Close all idle workers as soon as they are no longer needed.
Do not deviate from Engineering Plan 1.
Do not widen scope.
Execute only the phase specified in this document.

## Source of truth

Read the engineering plan from:

`root/docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`

Base all work on the actual live repository.
Inspect only what is needed to execute this phase cleanly and safely.
Do not infer permission for adjacent phase work.

## Worker governance

- Workers may inspect, propose, and implement only within the bounded phase scope.
- Workers must report back with:
  - files inspected
  - files added/modified
  - risks
  - scope-compliance status
- Reconcile all worker outputs centrally before finalizing.
- Revert or reject any worker output that widens scope.

## Coding standards

- correct indentation everywhere
- clean formatting
- readable naming
- explicit structure
- minimal, clean imports
- no brittle shortcuts
- no hidden behavior changes outside this phase
- preserve user-visible behavior unless the phase explicitly changes it
- follow repo conventions where they exist

## QA / QC requirements

### QC
- verify the engineering plan was read first
- verify scope remained limited to the current phase
- verify only phase-appropriate files and behaviors changed
- verify no adjacent-phase logic was implemented early
- verify worker scope stayed bounded
- verify changes align with the engineering plan exactly

### QA
- validate the phase outcome works as intended
- validate no unintended runtime regression was introduced
- validate the repository remains runnable and reviewable after this phase

If checks reveal scope creep, revert it and document it.

## Handoff requirements

Write a detailed handoff document after completing this phase.

### Handoff output location
`root/docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/`

If the folder does not exist yet, create it.

### Handoff content
The handoff must explain:
- what changed
- why it changed
- which files were added
- which files were modified
- whether any existing files were touched and why
- how scope was kept strictly within this phase
- what was intentionally not implemented yet
- what QA checks were performed
- what QC checks were performed
- whether any dormant imports, wrappers, seams, aliases, or deprecation markers were added
- confirmation that no adjacent-phase work was performed
- risks or follow-up notes for the next phase
- repo-specific conventions discovered that matter for later phases

## Milestone update requirement

On completion of this prompt, update:

`root/docs/change control/Milestones.md`

Rules:
- append only
- do not rewrite or reorder old milestone history
- create the file if it does not exist
- include the phase identifier, completion timestamp, completion status, and exception references if any
- maintain an `Exceptions` section
- use phase-based exception ids, for example `P1.3.1` for Plan 1 Phase 3 exception 1

## Final output expectation

When finished, provide:
1. a concise summary of what changed
2. confirmation that scope remained limited to this phase
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase
6. confirmation that the milestone was written to `Milestones.md`


## Task

Execute **Plan 1 / Phase 12 — Edit Dialog Extraction** only.

## Scope
- move `EditDialog`
- preserve compatibility alias
- use the previously introduced `TrackEditorHost`

## Allowed
- extraction into `isrc_manager/tracks/edit_dialog.py`
- compatibility imports/re-exports
- narrowly scoped host/adaptor work required by the move
- focused editor validation

## Not allowed
- no broader App decomposition
- no cleanup beyond what is strictly required by the move
- no Plan 2 work

## Validation
- edit and bulk edit workflows still function
- focused editor tests pass
- compile/import sanity passes

## Handoff filename
`P1 Phase 12 handoff.md`

## Execution order
1. Read the engineering plan
2. Confirm Phase 12 scope
3. Inspect edit dialog code only as needed
4. Execute Phase 12 only
5. Run phase-scoped validation
6. Perform QA/QC scope audit
7. Write the handoff
8. Update `Milestones.md`
9. Stop

### Final instruction
Execute only **Plan 1 / Phase 12**.

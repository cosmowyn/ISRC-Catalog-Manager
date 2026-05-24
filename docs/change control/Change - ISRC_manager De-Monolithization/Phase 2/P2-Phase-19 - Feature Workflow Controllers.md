# Codex Prompt — Execute Phase 19 Only

Act as a senior software engineer working directly in the live repository, with strong judgment for migration discipline, scope control, repository hygiene, QA/QC rigor, token-budget discipline, and production-grade code quality.

You are the central authority and final decision-maker for this task.
Use worker agents only as bounded support units.
Use a maximum of 6 worker agents.
Close all idle workers as soon as they are no longer needed.
Do not deviate from Engineering Plan 2.
Do not widen scope.
Execute only the phase specified in this document.

## Source of truth

Read the engineering plan from:

`root/docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`

Read the mandatory architecture enforcement plan from:

`root/docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`

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
- compatibility inventory change status
- root alias additions/removals
- deprecated wrapper additions/removals
- architecture boundary observations
- package parity impact
- import-cycle risk observations
- module-size / mini-monolith risk observations
- architecture metrics impact
- confirmation that no phase created permanent migration glue
- confirmation that any new compatibility alias has target path, deprecation policy, removal phase, and inventory entry
- confirmation that no adjacent-phase work was performed
- risks or follow-up notes for the next phase
- repo-specific conventions discovered that matter for later phases

## Milestone update requirement

On completion of this prompt, update:

`root/docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

Rules:
- append only
- do not rewrite or reorder old milestone history
- create the file if it does not exist
- include the phase identifier, completion timestamp, completion status, and exception references if any
- mention compatibility inventory status
- mention architecture metrics status when relevant
- maintain an `Exceptions` section
- use phase-based exception ids, for example `P2.15.1` for Plan 2 Phase 15 exception 1

## Final output expectation

When finished, provide:
1. a concise summary of what changed
2. confirmation that scope remained limited to this phase
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase
6. confirmation that the milestone was written to `root/docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`


## Task

Execute one named **Plan 2 / Phase 19 subphase** only.

## Scope
- choose exactly one named Phase 19 subphase from the engineering plan:
  - Phase 19A — Releases and Works Workflow Controllers
  - Phase 19B — Exchange, Master Transfer, Import, and Export Controllers
  - Phase 19C — Tags and Metadata Workflow Controllers
  - Phase 19D — Media Player, Bookmarks, Equalizer, Waveform Cache Orchestration, and Audio Export Controllers
  - Phase 19E — Audio Conversion, Watermarking, Authenticity, and Provenance Controllers
  - Phase 19F — Quality Workflow Controllers
  - Phase 19G — Update Workflow Controller Finalization
  - Phase 19H — Promo Code Workflow Controllers
  - Phase 19I — Contract Templates, Contracts, Rights, Assets, and Parties Controllers
- preserve user-visible behavior through delegation/shims
- update architecture metrics and compatibility inventory if affected

## Allowed
- one named subphase per Codex run
- controller/orchestration extraction into existing feature packages
- thin delegation shims in `App`
- focused validation for the selected feature family
- for Phase 19D only, media responsibility separation checks for visualization, preparation/preload, playback, and export

## Not allowed
- do not combine Phase 19 subphases unless a later planning document explicitly authorizes a combined run
- do not turn any subphase into a catch-all feature migration
- for Phase 19D, do not pull preview dialogs back into controller modules
- for Phase 19D, do not create a single media module that owns visualization, preparation/preload, playback, and export
- no final `App` move yet
- no final compatibility cleanup
- no Phase 20+ work

## Validation
- focused feature tests for the moved family pass
- compile/import sanity passes
- campaign gates at checkpoints as appropriate
- media-player/audio workflow tests after media controller batches
- update workflow tests after update controller batches
- architecture metrics and compatibility inventory status are documented

## Handoff filename
`P2 Phase 19<subphase-letter> handoff.md`

## Execution order
1. Read the engineering plan
2. Confirm the selected Phase 19 subphase
3. Inspect only the chosen subphase code as needed
4. Execute only the selected Phase 19 subphase
5. Run phase-scoped validation
6. Perform QA/QC scope audit
7. Write the handoff
8. Update `root/docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`
9. Stop

### Final instruction
Execute only the selected **Plan 2 / Phase 19 subphase**.

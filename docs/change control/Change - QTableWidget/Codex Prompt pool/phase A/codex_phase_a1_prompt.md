# Codex Prompt — Phase A1 Execution

Act as a senior software engineer working directly in the live repository, with strong judgment for migration discipline, scope control, repository hygiene, QA/QC rigor, and production-grade code quality.

You are the central authority and final decision-maker for this task.  
Use worker agents only as bounded support units.  
Use a maximum of 6 worker agents.  
Do not deviate from the engineering plan.  
Do not widen scope.  
Do not begin any Phase A2 or any Phase B work.  
Close all idle workers as soon as they are no longer needed.

## Task

Read the engineering plan from:

`root/docs/change control/Change - QTableWidget/Engineering plan.md`

Your task is to execute **Phase A1 only** from that plan.

### Phase A1 scope
- create `isrc_manager/catalog_table/`
- create all approved module files with class/function scaffolding
- create the public package surface
- allow only minimal dormant imports if needed
- keep runtime behavior unchanged

This is a controlled scaffolding phase only.

## Phase A1 Contract

Execute only the A1 batch defined in the engineering plan.

### A1 goals
- create the `isrc_manager/catalog_table/` package
- create all approved module files
- add class/function scaffolding according to the plan
- keep the new module surface structurally real and auditable
- do not change live application behavior
- do not wire production logic to the new modules yet

### Approved files to create
- `isrc_manager/catalog_table/__init__.py`
- `isrc_manager/catalog_table/models.py`
- `isrc_manager/catalog_table/table_model.py`
- `isrc_manager/catalog_table/filter_proxy.py`
- `isrc_manager/catalog_table/header_state.py`
- `isrc_manager/catalog_table/controller.py`
- `isrc_manager/catalog_table/zoom.py`

### Allowed
- package creation
- module creation
- class/function/type scaffolding
- docstrings
- comments
- dormant imports if needed
- non-invasive type-only seams if truly required
- tests only if they are strictly needed to validate A1 scaffolding/importability

### Not allowed
- no live cutover
- no runtime wiring
- no shell flip
- no model/view migration in production code
- no behavior changes
- no replacing monolith logic
- no header-state cutover
- no controller cutover
- no zoom cutover
- no cleanup/removal of existing monolith logic
- no partial implementation of A2, A3, B1, B2, B3, B4, B5, or B6

## Worker Governance

- Use a maximum of 6 worker agents.
- You remain the central authority and brain of the operation.
- Decompose work into bounded sub-tasks only if useful.
- Workers may inspect, propose, and scaffold within assigned scope.
- Workers must report back with:
  - files inspected
  - files created/modified
  - risks
  - scope-compliance status
- Do not allow workers to widen scope.
- Close all idle workers as soon as they are no longer needed.
- Do not keep unused workers alive.
- Reconcile all worker outputs centrally before finalizing.

### Suggested worker split if useful
- plan/path verification
- package/module scaffolding
- importability/compile validation
- QA/QC scope audit
- handoff drafting
- coding standards review

## Source of Truth Rules

- The engineering plan is the source of truth for scope and structure.
- Read the plan first.
- Base all work on the actual live repository.
- Inspect only what is needed to:
  - confirm the target doc path
  - confirm repository package layout
  - confirm import conventions
  - create the new package cleanly

Do not perform broad repo changes.  
Do not infer permission for later phases.

## Strict Scope Rules

Stay strictly inside A1.

That means:
- yes to structural scaffolding
- yes to auditable module surfaces
- yes to compile/import-safe class skeletons
- no to actual functional migration
- no to replacing current catalog logic
- no to changing live code paths to depend on the new modules
- no to marking monolith functions deprecated yet unless the plan explicitly requires that in A1
- no to dead code cleanup
- no to runtime behavior changes

If you encounter tempting adjacent work, document it in the handoff instead of implementing it.

## Scaffolding Requirements

Create the new package so it is clean, readable, and ready for later phased cutover.

### Expected structural content

- `models.py`
  - scaffold:
    - `CatalogColumnSpec`
    - `CatalogCellValue`
    - `CatalogRowSnapshot`
    - `CatalogSnapshot`
    - role constant declarations

- `table_model.py`
  - scaffold:
    - `CatalogTableModel(QAbstractTableModel)`
    - placeholder public methods:
      - `set_snapshot()`
      - `column_spec()`
      - `track_id_for_source_row()`
      - `source_row_for_track_id()`

- `filter_proxy.py`
  - scaffold:
    - `CatalogFilterProxyModel(QSortFilterProxyModel)`
    - placeholder public methods:
      - `set_search_text()`
      - `set_search_column_key()`
      - `set_explicit_track_ids()`

- `header_state.py`
  - scaffold:
    - `CatalogHeaderStateManager`

- `controller.py`
  - scaffold:
    - `CatalogTableController(QObject)`

- `zoom.py`
  - scaffold:
    - `CatalogZoomController(QObject)`

### Implementation level for A1
- enough structure that the modules are real, importable, and auditable
- enough typing/docstrings/comments that later phases have a clear landing zone
- not so much implementation that Phase A2/A3 work is accidentally pulled forward

Prefer clearly marked stubs/placeholders over speculative partial logic.

## Coding Standards

Adhere to the highest coding standards.

### Requirements
- correct indentation everywhere
- clean formatting
- readable naming
- explicit structure
- minimal, clean imports
- no dead random scaffolding
- no vague placeholder junk
- no misleading pseudo-implementation
- docstrings/comments should describe intended responsibility, not pretend the logic already exists
- keep the codebase clean and auditable

If the repo has existing style conventions, follow them.

## QA / QC Control Mechanisms

Implement explicit QA and QC controls to ensure the engineering plan is followed verbatim.

### QC requirements
- verify the engineering plan was read first
- verify only A1-approved files are created
- verify no runtime path was switched to depend on the new package
- verify no live behavior changed
- verify no later-phase logic was implemented early
- verify new modules are structurally aligned with the plan
- verify importability / compile sanity of the new package
- verify worker scope stayed bounded

### QA requirements
- validate the new package can be imported cleanly
- validate repository still runs at the same behavior level as before, to the extent checkable without widening scope
- validate no accidental shell/UI/runtime wiring was introduced
- validate A1 remains structurally real but runtime-dormant

If checks reveal scope creep, revert it and document it.

## Validation Requirements

A1 validation should stay within scope.

### Required validation
- path/package exists as planned
- modules import or compile cleanly
- no runtime behavior changed
- no production dependency on the new modules was introduced unless truly dormant and harmless
- package is ready for later A2/A3 work

Do not start writing full implementation tests for later phases.  
Do not create broad regression work outside A1 unless needed to prove A1 did not affect runtime behavior.

## Handoff Requirements

Write a detailed handoff document after completing A1.

### Handoff output location
Write the handoff document to:

`root/docs/change control/Change - QTableWidget/phase execution handoffs/`

If the folder does not exist yet, create it.

### Handoff file naming rule
Name the handoff file exactly:

`A1 handoff.md`

Do not use any other file name.  
Do not merge this handoff with any other phase handoff.  
Do not place the handoff anywhere else unless the task explicitly says otherwise.

The handoff must explain:
- what was created
- why it was created
- which files were added
- which files were modified
- whether any existing files were touched and why
- how scope was kept strictly within A1
- what was intentionally not implemented yet
- what QA checks were performed
- what QC checks were performed
- whether any dormant imports or seams were added
- confirmation that live behavior was not cut over
- confirmation that no adjacent-phase work was performed
- risks or follow-up notes for A2/A3
- any repo-specific conventions discovered that matter for later phases

The handoff must be detailed enough that the next engineer or Codex pass can start A2 or A3 without rediscovering context.

## Execution Order

Follow this order exactly:

1. Read `root/docs/change control/Change - QTableWidget/Engineering plan.md`
2. Confirm A1 scope from the plan
3. Inspect the repository only as needed for package/layout conventions
4. Create the new `isrc_manager/catalog_table/` package and approved files
5. Keep implementation strictly at scaffolding level
6. Run A1-scoped validation and import/compile checks
7. Perform QA/QC scope audit
8. Write the detailed handoff document
9. Update `root/docs/change control/Milestones.md`
10. Stop

## Completion Contract

Do not consider the task complete until all of the following are true:

- engineering plan was read
- scope remained A1-only
- `isrc_manager/catalog_table/` exists
- all approved A1 files exist
- scaffolding is clean and auditable
- no live runtime cutover occurred
- no later-phase work was implemented
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

- `A1 — completed — 18-apr-2026 14:32`
- `Exceptions: none`

or, if exceptions occurred:

- `A1 — completed with exceptions — 18-apr-2026 14:32`
- `Exceptions: A1.1, A1.2`

### Exceptions section
Also maintain an `Exceptions` section in the same document.

Rules:
- create the `Exceptions` section if it does not yet exist
- append new exceptions after any existing exceptions
- do not renumber old exceptions
- each exception must use a phase-based reference with a follow number, for example:
  - `A1.1`
  - `A1.2`
  - `B3.1`

For each exception, record:
- the exception reference
- the phase
- a short description of what happened
- whether it was resolved in the current phase or remains open

Example:

- `A1.1 — Phase A1 — import scaffold required one dormant compatibility import — resolved`
- `B3.1 — Phase B3 — proxy/source mapping bug discovered during validation — open`

### Scope discipline
- Only record the phase that was actually executed by the current prompt.
- Do not mark future phases as complete.
- Do not rewrite milestone history beyond appending the new completed phase entry and any new exceptions.

## Final Output Expectation

When finished, provide:
1. a concise summary of what was created
2. confirmation that scope remained A1-only
3. QA/QC summary
4. the handoff document path
5. any follow-up notes for the next phase
6. confirmation that the milestone was written to `Milestones.md`

### Final instruction
Execute only Phase A1 from the engineering plan.  
Do not implement the migration.  
Do not wire live behavior to the new modules.  
Be strict, auditable, and disciplined.
# Contract Template Placeholder Workflow - Phase 5 Handoff

## Phase Goal

Land editable draft save/resume for the placeholder-driven fill workflow.

Phase 5 scope:
- save fill-state drafts from the `Fill Form` workspace
- reopen drafts and restore live widget state
- keep draft storage mode explicit as `database` or `managed_file`
- preserve the distinction between mutable drafts and immutable snapshot/artifact records

Out of scope for this phase:
- placeholder resolution into final document content
- PDF export
- admin/archive cleanup tooling beyond the draft list already present in the fill workspace

## What Was Implemented

### 1. Fill-workspace draft session flow

Expanded [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py) so the `Fill Form` tab now has a working draft session surface:
- revision-scoped draft listing
- draft name editing
- storage-mode selection
- `Save New Draft`
- `Save Draft Changes`
- `Load Selected Draft`
- `Reset Form`

The panel now:
- refreshes drafts per selected revision
- keeps the saved or loaded draft selected in the combo
- restores `db_selections` and `manual_values` back into live widgets
- clears only the live form on reset while leaving persisted drafts intact
- updates the user-facing status label during save/load/reset actions

### 2. Explicit state restore for manual widgets

Phase 5 tightened value restoration in [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py):
- selector combos restore by item data rather than display text
- date widgets restore explicit dates and preserve touched-state semantics
- number widgets restore explicit `0`
- boolean widgets restore explicit `False`

This also fixed a real widget bug from the Phase 4 surface: boolean manual fields now render as checkboxes before option-driven widgets are considered, so draft payloads no longer collapse boolean intent into option-combo behavior.

### 3. Revision-filtered draft service seam

Confirmed and retained the Phase 5 draft backend in [service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/service.py), with `list_drafts(...)` now supporting `revision_id` filtering for the workspace.

This keeps the fill panel honest:
- drafts are listed only for the active revision
- loading a draft switches to the matching template/revision context before payload hydration
- updating a draft reuses the existing row instead of duplicating draft records

### 4. App-shell workflow coverage

Extended the real docked-app coverage in:
- [tests/app/_app_shell_support.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [tests/app/test_app_shell_workspace_docks.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

The contract template workspace is now verified through the real app shell for:
- opening on the fill tab
- saving a draft
- resetting the form
- reloading the saved draft
- restoring name, storage mode, and field values while the dock remains tabified with the catalog workspace

## Source-Of-Truth Files / Surfaces

Primary runtime surfaces:
- [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py)
- [service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/service.py)

Primary test surfaces:
- [test_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_dialogs.py)
- [test_contract_template_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_contract_template_service.py)
- [tests/app/_app_shell_support.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [tests/app/test_app_shell_workspace_docks.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

## Tests Added / Updated

Updated:
- [test_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_dialogs.py)
- [test_contract_template_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_contract_template_service.py)
- [tests/app/_app_shell_support.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [tests/app/test_app_shell_workspace_docks.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

Verification run for Phase 5:
- `python3 -m py_compile isrc_manager/contract_templates/dialogs.py isrc_manager/contract_templates/service.py tests/contract_templates/test_dialogs.py tests/test_contract_template_service.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py`
- `python3 -m unittest tests.contract_templates.test_dialogs tests.test_contract_template_service`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.contract_templates.test_form_generation tests.contract_templates.test_revision_service tests.contract_templates.test_scanner`
- `python3 -m unittest tests.test_contract_template_parser tests.test_contract_template_service tests.contract_templates.test_scanner tests.contract_templates.test_revision_service tests.contract_templates.test_catalog tests.contract_templates.test_form_generation tests.contract_templates.test_dialogs`
- `python3 -m unittest tests.app.test_app_shell_startup_core tests.app.test_app_shell_workspace_docks`

All commands passed during Phase 5 verification.

## Deferred Items

Deferred to Phase 6:
- resolve placeholders into final document content
- create immutable resolved snapshots from real export runs
- generate and track PDF artifacts
- add admin/archive/cleanup tools for templates, drafts, snapshots, and artifacts

## Risks / Caveats

- Draft reset is now immediate in the docked workspace. That keeps the non-modal workflow responsive and testable, but it also means there is no confirmation barrier before clearing the current live form.
- Drafts remain revision-scoped. If Phase 6 introduces richer scope selection or preview resolution, the load flow must keep switching into the correct revision context before applying payloads.
- The draft workflow currently preserves editable payload state only. It does not preview resolved output, validate export readiness, or create snapshots on save.
- Mutable draft rows and immutable snapshot/artifact rows are still separated correctly at the storage layer, but that separation only becomes user-visible once Phase 6 lands export flows.

## Worker List And Closures

Planning / review workers:
- `Boyle` - completed, reconciled, closed
- `Darwin` - completed, reconciled, closed
- `Dalton` - completed, reconciled, closed

## QA / QC Summary

Central Oversight checks completed:
- kept the workflow placeholder-template-first and did not reintroduce builder-first authoring
- kept Phase 5 inside the existing contract template workspace rather than creating a disconnected draft editor
- ensured revision filtering keeps the draft list honest and avoids cross-revision leakage
- verified editable payload resume through both panel-level tests and a real app-shell dock workflow
- fixed boolean manual-field rendering so stored draft values round-trip as booleans instead of option-like strings
- preserved the storage separation between mutable drafts and later snapshot/artifact layers

## Exact Safe Pickup Instructions For Phase 6

1. Start from the Phase 5 branch state after these changes are committed.
2. Use [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py) as the live fill-state source and [service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/service.py) as the mutable draft store.
3. Add a resolver/export layer that turns a saved or in-memory editable payload into resolved placeholder values.
4. Persist immutable resolved snapshots separately from drafts before writing PDF artifacts.
5. Add at least one operational PDF renderer path for the supported template family.
6. Keep cleanup semantics explicit about whether deleting a record only removes DB rows or also deletes managed files on disk.

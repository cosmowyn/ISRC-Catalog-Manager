# Contract Template Placeholder Workflow - Phase 4 Handoff

## Phase Goal

Land the first real dynamic fill-form workflow for placeholder-driven contract templates.

Phase 4 scope:
- build a form definition from persisted placeholder inventories
- map known `db.*` placeholders to selector-driven controls
- map `manual.*` placeholders to typed manual inputs
- preserve repeated-placeholder dedupe so one canonical symbol becomes one control
- expose the fill workflow inside the existing contract template workspace dock

Out of scope for this phase:
- draft save/resume UX
- managed-vs-embedded draft decisions in the UI
- resolved document generation
- PDF export
- admin/archive tooling beyond what already existed

## What Was Implemented

### 1. Form-definition service

Added a new service surface at [form_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/form_service.py).

Key behavior:
- synchronizes placeholder bindings from the persisted revision inventory plus catalog metadata
- builds `ContractTemplateFormDefinition` records for a revision
- creates selector fields for `db.*` placeholders using catalog scope/type metadata
- creates typed manual fields for `manual.*` placeholders
- applies manual type inference for date, number, boolean, and text
- returns editable payloads shaped for Phase 5 draft persistence

### 2. Phase 4 domain dataclasses

Extended [models.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/models.py) with:
- `ContractTemplateFormChoice`
- `ContractTemplateFormSelectorField`
- `ContractTemplateFormManualField`
- `ContractTemplateFormDefinition`

These are now the source-of-truth records for the generated fill surface.

### 3. Binding replacement seam

Extended [service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/service.py) with `replace_placeholder_bindings(...)` so Phase 4 can rebuild binding metadata for an existing revision without re-importing the template source.

### 4. Workspace integration

Expanded [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py) from a symbol-only panel into a two-tab workspace:
- `Symbol Generator`
- `Fill Form`

The new fill tab now:
- lists available templates and revisions
- rebuilds a form from the selected scanned revision
- renders selector widgets for DB-backed placeholders
- renders typed manual widgets for manual placeholders
- exposes `current_fill_state()` as a Phase 5-ready editable payload seam

### 5. App-shell wiring

Updated [ISRC_manager.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py) to instantiate and lifecycle-manage:
- `ContractTemplateService`
- `ContractTemplateFormService`

The dock factory now passes catalog, template, and form providers into the contract template workspace. `open_contract_template_workspace(initial_tab="fill")` now routes to a real fill tab.

### 6. Public exports

Updated:
- [contract_templates/__init__.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/__init__.py)
- [services/__init__.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/services/__init__.py)

These now export the Phase 4 form service and form dataclasses.

## Source-Of-Truth Files / Surfaces

Primary runtime surfaces:
- [form_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/form_service.py)
- [models.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/models.py)
- [service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/service.py)
- [dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/dialogs.py)
- [ISRC_manager.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)

Public export surfaces:
- [contract_templates/__init__.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/__init__.py)
- [services/__init__.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/services/__init__.py)

Primary test surfaces:
- [test_form_generation.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_form_generation.py)
- [test_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_dialogs.py)
- [test_catalog.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_catalog.py)
- [test_revision_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_revision_service.py)
- [tests/app/_app_shell_support.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [tests/app/test_app_shell_workspace_docks.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

## Tests Added / Updated

Added:
- [test_form_generation.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_form_generation.py)

Updated:
- [test_dialogs.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_dialogs.py)
- [test_catalog.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_catalog.py)
- [test_revision_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/contract_templates/test_revision_service.py)
- [tests/app/_app_shell_support.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
- [tests/app/test_app_shell_workspace_docks.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/app/test_app_shell_workspace_docks.py)

Verification run for Phase 4:
- `python3 -m py_compile isrc_manager/contract_templates/dialogs.py isrc_manager/contract_templates/form_service.py isrc_manager/contract_templates/__init__.py isrc_manager/services/__init__.py ISRC_manager.py`
- `python3 -m unittest tests.contract_templates.test_form_generation tests.contract_templates.test_catalog tests.contract_templates.test_revision_service tests.contract_templates.test_dialogs`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.test_contract_template_parser tests.test_contract_template_service tests.contract_templates.test_scanner tests.contract_templates.test_revision_service tests.contract_templates.test_form_generation tests.contract_templates.test_dialogs`
- `python3 -m unittest tests.app.test_app_shell_startup_core`

All commands passed during Phase 4 verification.

## Deferred Items

Deferred to Phase 5:
- save draft from the fill workspace
- reopen draft and restore editable state into live widgets
- managed-file versus database-backed draft save options in the UI
- scope-aware resume flows tied to a chosen entity context

Deferred to Phase 6:
- resolved placeholder replacement into final document content
- PDF generation
- output artifact tracking in the UI
- admin/archive/cleanup tooling for templates, drafts, snapshots, and artifacts

## Risks / Caveats

- The fill tab is real, but it is still a Phase 4 form-building surface only. Users can produce an editable payload via the generated controls, but Phase 5 still has to persist and restore that state.
- DB-backed placeholders currently render as selector controls driven by available records. There is no advanced search dialog or scoped chooser yet.
- Track-context selectors are picker-driven and catalog-safe, but they do not yet layer in richer selection-scope override UX like the release/work managers.
- Manual date and number widgets intentionally preserve a “not yet touched” state so blank values do not become accidental defaults. Phase 5 must keep that behavior when drafts are loaded back in.

## Worker List And Closures

Planning / architecture workers:
- `Pascal` - completed, reconciled, closed
- `Cicero` - completed, reconciled, closed
- `Singer` - errored during planning attempt, closed intentionally after reconciliation

Implementation worker:
- `Turing` - completed targeted test-surface work, reconciled, closed

## QA / QC Summary

Central Oversight checks completed:
- preserved the placeholder-template pivot and did not reintroduce any builder-first or HTML-first authoring path
- kept the workspace coherent by adding the fill flow to the existing contract template dock instead of creating a disconnected utility
- used persisted placeholder rows as the Phase 4 source of truth, not raw scan occurrences
- preserved canonical-symbol dedupe so repeated placeholders stay one-control-per-symbol
- kept DB-backed data picker-driven and manual data explicitly typed
- kept Phase 5 and Phase 6 concerns out of this landing

## Exact Safe Pickup Instructions For Phase 5

1. Start from the Phase 4 branch state after these changes are committed.
2. Use [form_service.py](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contract_templates/form_service.py) and `ContractTemplateWorkspacePanel.current_fill_state()` as the Phase 5 payload seam.
3. Add draft save/load actions to the `Fill Form` tab, backed by existing `ContractTemplateService.create_draft(...)`, `update_draft(...)`, and `fetch_draft_payload(...)`.
4. Restore saved `db_selections` and `manual_values` into live widgets when reopening a draft.
5. Keep managed-file versus database-backed draft storage explicit and honest in the UI.
6. Do not add PDF generation or resolved export logic during Phase 5.

# Contract Template Placeholder Phase 3

Current product version: `2.0.0`

Date: 2026-03-25

## Status And Scope

Phase 3 is complete.

This pass stayed in symbol-generator workspace and mapping-dictionary scope only.

It did:

- add a catalog-backed symbol registry for canonical `db.*` placeholders and manual-symbol generation
- add a docked Contract Template Workspace focused on symbol generation rather than layout authoring
- wire that workspace into the existing catalog workspace shell and menu structure
- add focused catalog, widget, workspace-dock, and startup-shell tests

It did not:

- add template fill forms
- add DB value resolution
- add draft editing or resume flows
- add preview rendering
- add PDF export

## Phase Goal

Land the Phase 3 symbol generator so users can browse valid canonical placeholders from real repo-backed fields, generate safe manual placeholders, and access that workflow as a coherent workspace inside the app without drifting back toward a builder-first contract editor.

## What Was Implemented In This Pass

- added `isrc_manager.contract_templates.catalog` with:
  - `ContractTemplateCatalogService`
  - namespace-aware symbol listing for `track`, `release`, `work`, `contract`, `party`, `right`, `asset`, and `custom`
  - `ContractTemplateCatalogSection`
  - manual placeholder normalization via `{{manual.some_key}}`
- extended catalog entry models with:
  - `ContractTemplateCatalogEntry`
  - source-kind and label helpers for UI/detail presentation
- anchored the catalog to real repo surfaces:
  - `STANDARD_FIELD_SPECS`
  - release/work/contract/party/right/asset choice constants
  - active custom fields from `CustomFieldDefinitionService`
- normalized source metadata where Phase 2 caveats mattered:
  - track join/read-model fields such as `artist_name`, `album_title`, and `additional_artists` now point at the track snapshot authority rather than pretending they are raw `Tracks` columns
  - `release.notes` now points to `Releases.release_notes`
- added `isrc_manager.contract_templates.dialogs.ContractTemplateWorkspacePanel` with:
  - a dock-friendly tabbed workspace shell
  - searchable namespace filtering
  - copy-selected and copy-visible symbol actions
  - selected-symbol detail inspection
  - manual symbol helper and clipboard copy path
- integrated the new workspace into the app shell:
  - new `Catalog > Workspace > Contract Template Workspace…` action
  - `open_contract_template_workspace(...)`
  - persistent dock-shell registration
  - service initialization/reset wiring for `ContractTemplateCatalogService`
- kept the implementation explicitly out of builder/editor territory; the workspace is a symbol generator and mapping dictionary only

## Source Of Truth Files And Surfaces

Primary implementation files for Phase 3:

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/catalog.py`
- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/services/__init__.py`

Primary test surfaces for Phase 3:

- `tests/contract_templates/test_catalog.py`
- `tests/contract_templates/test_dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/app/test_app_shell_startup_core.py`

## Files Changed

- `ISRC_manager.py`
- `docs/implementation_handoffs/contract-template-placeholder-phase-3.md`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/catalog.py`
- `isrc_manager/contract_templates/dialogs.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/services/__init__.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/contract_templates/test_catalog.py`
- `tests/contract_templates/test_dialogs.py`

## Tests Added Or Updated

Added:

- `tests/contract_templates/test_catalog.py`
- `tests/contract_templates/test_dialogs.py`

Updated:

- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_workspace_docks.py`

## Validation Performed

Commands run during Phase 3 verification:

- `python3 -m py_compile isrc_manager/contract_templates/catalog.py isrc_manager/contract_templates/dialogs.py ISRC_manager.py tests/contract_templates/test_catalog.py tests/contract_templates/test_dialogs.py tests/app/_app_shell_support.py tests/app/test_app_shell_workspace_docks.py`
- `python3 -m unittest tests.contract_templates.test_catalog tests.contract_templates.test_dialogs`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.test_contract_template_parser tests.test_contract_template_service tests.contract_templates.test_scanner tests.contract_templates.test_revision_service tests.contract_templates.test_catalog tests.contract_templates.test_dialogs`
- `python3 -m unittest tests.app.test_app_shell_startup_core`

All passed.

## What Was Intentionally Deferred

- dynamic fill-form generation from detected placeholders
- DB-backed picker widgets and resolver execution
- smart manual-field typing and form inference
- draft save/resume UX
- resolved-document snapshots for editing workflows
- PDF export and output artifact generation
- template/draft admin cleanup UI

## Risks And Caveats

- the symbol catalog is authoritative for placeholder generation, but it does not yet resolve live values; Phase 4 must still decide the actual widget/resolver behavior per placeholder
- `db.custom` remains track-scoped because the current `CustomFieldValues` schema is track-bound
- the workspace currently has one operational tab, `Symbol Generator`; that is intentional for Phase 3 and avoids inventing premature builder-style surfaces
- source metadata shown in the dictionary is meant to be honest about authority, not necessarily limited to a single raw table column; track-facing joined fields therefore point at the track snapshot/read surface

## Worker List And Closures

Central oversight used the following planning and implementation workers and closed them after reconciliation:

- `Rawls` - app-shell workspace integration review - closed
- `Volta` - authoritative symbol catalog and field-source review - closed
- `Lorentz` - Phase 3 package/test-shape review - closed

## QA/QC Summary From Central Oversight

Central oversight conclusions:

- the pivot remains placeholder-template-first; no builder UI, HTML authoring path, or visual contract editor leaked back into the implementation
- Phase 3 now gives the app a coherent internal workspace for symbol generation while keeping external Word/Pages documents as the layout source of truth
- the symbol dictionary is anchored to real repo-backed fields, choice lists, and custom-field definitions rather than guessed names
- custom blob/media fields remain excluded from copy-ready placeholder generation
- shell integration follows the existing docked workspace pattern, and direct widget plus app-shell tests keep the feature from becoming an untracked utility sidecar

## Exact Safe Pickup Instructions For Phase 4

Start Phase 4 with dynamic fill-form generation and smart type logic.

Do this next:

1. use scanned placeholder inventories plus the Phase 3 catalog to decide which placeholders are DB-backed and which are manual
2. generate one deduplicated input control per canonical placeholder
3. map known `db.*` placeholders to explicit selectors or pickers tied to the right entity scope
4. infer sensible manual widget types for `manual.*` placeholders such as text, date, number, and boolean/option
5. add tests for:
   - deduplicated repeated placeholders
   - DB-backed selector choice generation
   - manual type inference behavior
   - mixed DB/manual placeholder forms

Do not do this in Phase 4:

- do not add PDF export yet
- do not skip deduplication and create duplicate controls for the same canonical symbol
- do not guess DB resolver targets from arbitrary free-form placeholder names
- do not reintroduce any builder-first or free-form layout editor surface

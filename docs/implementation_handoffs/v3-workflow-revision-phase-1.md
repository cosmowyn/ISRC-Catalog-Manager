# V3 Workflow Revision Phase 1

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 1 is in progress.

This pass landed the first bounded Party-authority slice only:

- owner settings now support a canonical linked `Party`
- owner template/export resolution can hydrate from that linked `Party`
- the Application Settings owner tab now exposes Party-first linking and quick-create/edit actions
- Work Manager contributor rows now use Party-first selectors with quick-create/edit support and payload round-tripping of `party_id`
- Contract Manager linked-party entry now exposes Party quick-create/edit actions and clearer Party-first guidance while preserving transitional typed fallback

This pass did not complete the full Phase 1 Party cutover across all remaining identity-bearing surfaces.

## Phase Goal

Make identity-bearing workflow paths Party-first across the targeted v3 governance surfaces.

## What Changed

- added `owner_party_id` support to the owner settings read and write path
- made `SettingsReadService.load_owner_party_settings()` resolve from `Parties` first when `owner_party_id` is present, while keeping legacy `owner_*` profile values as a fallback snapshot
- extended `ApplicationSettingsDialog` so the `Owner Party` tab can link to an existing Party, quick-create a new Party, edit the linked Party, or clear the link
- locked owner identity fields to the linked Party when a canonical Party is selected
- preserved the public `{{db.owner.*}}` placeholder surface so contract-template exports and form generation continue to resolve through `OwnerPartySettings`
- replaced Work contributor name-only entry with a Party-backed editable selector that preserves `party_id` through `WorkEditorDialog.payload()`
- added in-dialog Party quick-create and edit actions for contributor rows so canonical identities can be created without leaving the Work flow
- kept typed contributor names as an explicit fallback when no Party is selected, so the Phase 1 cutover stays bounded while moving the default path to Party-first
- tightened contributor payload resolution so the UI can show disambiguating legal-name labels without storing those helper labels as the credited display name
- extended the contract linked-party editor with `New Party...` and `Edit Linked Party...` actions backed by the canonical `PartyService`
- refreshed contract-party choice lists from live Party records after quick-create/edit so the contract editor stays in sync without reopening
- updated contract-party guidance copy so the UI explicitly frames Party selection as the default path and typed names as a transitional fallback

## Source Of Truth Files And Surfaces

Primary Phase 1 surfaces for this slice:

- `ISRC_manager.py`
- `isrc_manager/services/settings_reads.py`
- `isrc_manager/services/settings_mutations.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/parties/dialogs.py`
- `isrc_manager/contract_templates/export_service.py`
- `isrc_manager/contract_templates/form_service.py`
- `tests/test_settings_read_service.py`
- `tests/test_settings_mutations_service.py`
- `tests/contract_templates/test_export_service.py`
- `tests/contract_templates/test_form_generation.py`
- `tests/test_theme_builder.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/contracts/dialogs.py`
- `tests/test_repertoire_dialogs.py`
- `tests/test_work_and_party_services.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/catalog/test_contract_dialogs.py`

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/services/settings_reads.py`
- `isrc_manager/services/settings_mutations.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/contracts/dialogs.py`
- `tests/test_settings_read_service.py`
- `tests/test_settings_mutations_service.py`
- `tests/contract_templates/test_export_service.py`
- `tests/test_repertoire_dialogs.py`
- `tests/test_theme_builder.py`
- `tests/test_work_and_party_services.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/catalog/test_contract_dialogs.py`

## Tests Added Or Updated

- `tests/test_settings_read_service.py`
  - added Party-backed owner hydration coverage
- `tests/test_settings_mutations_service.py`
  - added `owner_party_id` persistence and clear-link coverage
- `tests/contract_templates/test_export_service.py`
  - added owner-placeholder export coverage for linked owner Party resolution
- `tests/test_theme_builder.py`
  - added Application Settings owner-tab coverage for a linked Party selector
- `tests/test_repertoire_dialogs.py`
  - added Work editor coverage for Party-linked contributor round-tripping and typed-name fallback
- `tests/test_work_and_party_services.py`
  - added coverage proving `WorkService` reuses a supplied canonical `party_id` instead of creating duplicate Party rows
- `tests/catalog/_contract_rights_asset_support.py`
  - added contract-party quick-create/edit coverage against the live `ContractEditorDialog`
- `tests/catalog/test_contract_dialogs.py`
  - exposed the new contract-party quick-create/edit case in the dialog suite

Validation also reran:

- `tests/contract_templates/test_form_generation.py`

## Validation Performed

Commands run during this slice:

- `python3 -m unittest tests.test_settings_read_service tests.test_settings_mutations_service tests.contract_templates.test_export_service tests.contract_templates.test_form_generation tests.test_theme_builder`
- `python3 -m unittest tests.test_repertoire_dialogs tests.test_work_and_party_services`
- `python3 -m unittest tests.catalog.test_contract_dialogs`
- `python3 -m unittest tests.test_repertoire_dialogs tests.test_work_and_party_services tests.test_repertoire_status_service tests.test_quality_service tests.catalog.test_contract_dialogs`

Result:

- the targeted owner-settings, Work contributor, and Contract Manager Party-bridge suites passed

## What Was Intentionally Deferred

- broader rights/work/contract identity-surface cleanup remains for the rest of Phase 1
- work-parent and track-child schema revision remains deferred to Phase 2
- track creation workflow rewrite remains deferred to Phase 3
- legacy license removal remains deferred to Phase 5

## Risks And Caveats

- this is a lazy in-place migration: older profiles without `owner_party_id` still resolve through legacy `owner_*` settings until the user links a Party
- owner registration numbers (`vat_number`, `pro_number`, `ipi_cae`) still come from `General > Registration & Codes`, not from Party rows
- the `{{db.owner.*}}` contract-template surface still reads as “Application Settings > Owner Party” even though the backing source can now be a canonical Party
- Work contributor rows now default to Party-first selection, but they still allow typed fallback because the broader v3 contribution ledger redesign is deferred
- Contract Manager now guides users toward Party-first entry and supports in-flow quick-create/edit, but typed fallback still exists as an intentional transitional path
- Rights dialogs still lack the same level of in-flow Party quick-create/edit support, so Phase 1 is not ready to close yet

## Workers Used And Workers Closed

Phase 1 helpers used under central oversight:

- `Popper`
  - inspected settings read/write seams and recommended the `owner_party_id` bridge
  - closed after reconciliation
- `Poincare`
  - inspected the Application Settings owner tab and save path
  - closed after reconciliation
- `Planck`
  - inspected downstream contract-template owner resolution and compatibility pressure
  - closed after reconciliation
- `McClintock`
  - confirmed the Work editor UI was the Phase 1 gap and scoped the safest test seam
  - closed after reconciliation
- `Nietzsche`
  - confirmed `WorkService` was already Party-first at the persistence layer and pointed implementation at the dialog layer
  - closed after reconciliation

## QA/QC Summary From Central Oversight

Central-oversight conclusions for this slice:

- owner settings were the safest first Phase 1 cutover because they are identity-bearing, app-wide, and already feed template/export surfaces
- the new linked-owner flow establishes a real Party-first path without breaking the current `{{db.owner.*}}` namespace
- Work contributor entry is now Party-first in the Work editor, which removes the largest remaining Work-side identity mismatch between UI and persistence
- Contract Manager now has an in-flow canonical Party path instead of pushing users toward typed counterparties first
- the repo still has remaining Phase 1 identity debt in rights-side Party creation/edit flows and any remaining free-text identity seams, so Phase 1 should remain open until those are either reduced or explicitly deferred

## Exact Safe Pickup Instructions

Continue Phase 1 with Rights dialog Party quick-create/edit next, then reassess whether Phase 1 can close.

Do this next:

1. inspect `isrc_manager/rights/dialogs.py` and the related rights dialog tests
2. add in-flow Party quick-create/edit support so rights grants can resolve from canonical Party records without leaving the rights workflow
3. preserve current rights reference selection behavior while reducing duplicate identity paths
4. add tests before changing other governance surfaces:
   - rights dialog Party quick-create/edit behavior
   - any downstream validation that depends on selected Party IDs
5. reassess whether the remaining Phase 1 identity seams are small enough to close the phase or should be documented as deferred

Do not do this yet:

- do not start the Phase 2 work/track schema rewrite
- do not mix in track creation workflow changes
- do not remove license tables during Phase 1

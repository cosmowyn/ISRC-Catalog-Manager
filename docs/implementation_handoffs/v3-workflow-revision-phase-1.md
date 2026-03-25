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

This pass did not complete the full Phase 1 Party cutover across all remaining identity-bearing surfaces.

## Phase Goal

Make identity-bearing workflow paths Party-first across the targeted v3 governance surfaces.

## What Changed

- added `owner_party_id` support to the owner settings read and write path
- made `SettingsReadService.load_owner_party_settings()` resolve from `Parties` first when `owner_party_id` is present, while keeping legacy `owner_*` profile values as a fallback snapshot
- extended `ApplicationSettingsDialog` so the `Owner Party` tab can link to an existing Party, quick-create a new Party, edit the linked Party, or clear the link
- locked owner identity fields to the linked Party when a canonical Party is selected
- preserved the public `{{db.owner.*}}` placeholder surface so contract-template exports and form generation continue to resolve through `OwnerPartySettings`

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

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/services/settings_reads.py`
- `isrc_manager/services/settings_mutations.py`
- `tests/test_settings_read_service.py`
- `tests/test_settings_mutations_service.py`
- `tests/contract_templates/test_export_service.py`
- `tests/test_theme_builder.py`

## Tests Added Or Updated

- `tests/test_settings_read_service.py`
  - added Party-backed owner hydration coverage
- `tests/test_settings_mutations_service.py`
  - added `owner_party_id` persistence and clear-link coverage
- `tests/contract_templates/test_export_service.py`
  - added owner-placeholder export coverage for linked owner Party resolution
- `tests/test_theme_builder.py`
  - added Application Settings owner-tab coverage for a linked Party selector

Validation also reran:

- `tests/contract_templates/test_form_generation.py`

## Validation Performed

Commands run during this slice:

- `python3 -m unittest tests.test_settings_read_service tests.test_settings_mutations_service tests.contract_templates.test_export_service tests.contract_templates.test_form_generation tests.test_theme_builder`

Result:

- the targeted Phase 1 owner-settings Party-bridge suite passed

## What Was Intentionally Deferred

- Work contributor rows still need a Party-first selector path in `Work Manager`
- contract-party free-text fallback cleanup was not revisited in this slice
- broader rights/work/contract identity-surface cleanup remains for the rest of Phase 1
- work-parent and track-child schema revision remains deferred to Phase 2
- track creation workflow rewrite remains deferred to Phase 3
- legacy license removal remains deferred to Phase 5

## Risks And Caveats

- this is a lazy in-place migration: older profiles without `owner_party_id` still resolve through legacy `owner_*` settings until the user links a Party
- owner registration numbers (`vat_number`, `pro_number`, `ipi_cae`) still come from `General > Registration & Codes`, not from Party rows
- the `{{db.owner.*}}` contract-template surface still reads as “Application Settings > Owner Party” even though the backing source can now be a canonical Party
- Work Manager contributor rows are still the clearest remaining Party-first gap in the current repo

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

## QA/QC Summary From Central Oversight

Central-oversight conclusions for this slice:

- owner settings were the safest first Phase 1 cutover because they are identity-bearing, app-wide, and already feed template/export surfaces
- the new linked-owner flow establishes a real Party-first path without breaking the current `{{db.owner.*}}` namespace
- the repo still has remaining Phase 1 identity debt, especially in Work contributor entry flows, so Phase 1 should remain open until that gap is addressed or explicitly deferred

## Exact Safe Pickup Instructions

Continue Phase 1 with Work contributor Party-first entry next.

Do this next:

1. inspect `isrc_manager/works/dialogs.py` and `isrc_manager/works/service.py`
2. replace contributor name-only entry with Party-first selection plus quick-create where practical
3. preserve contributor-role and split validation behavior while making `party_id` the default identity path
4. add tests before changing other governance surfaces:
   - work dialog contributor entry
   - work service payload persistence
   - integration coverage where linked works already feed quality/search
5. reassess whether contract-party free-text fallback should be narrowed before closing Phase 1

Do not do this yet:

- do not start the Phase 2 work/track schema rewrite
- do not mix in track creation workflow changes
- do not remove license tables during Phase 1

# V3 Track-First Governed Creation Correction

Date: 2026-03-25

Status: `completed / active source of truth`

## Purpose

Correct the earlier v3 creation-direction assumption that `Work Manager` should be the main user-facing creation start.

That assumption is now superseded.

The active v3 product model is:

- `Add Track` is the primary single-item musical creation entry point
- `Add Album` is the primary batch musical creation entry point
- every new track must immediately resolve Work governance
- `Work Manager` remains the governance and management surface after or alongside track-first entry

## Incorrect Prior Assumption

The prior v3 direction over-weighted `Work Manager` and the `Create Musical Entry` chooser as the normal start for new musical items.

That created the wrong product shape:

- it made `Work Manager` feel like the main creation start instead of the governance manager
- it demoted `Add Track` too far
- it treated `Add Album` as something downstream of a separate chooser flow
- it left the shell, help, and tests anchored to the wrong concept even after inline governed track creation started to exist

## Corrected Product Model

The corrected v3 creation model is now:

- `Add Track` starts single-item musical entry
- `Add Album` starts batch musical entry
- each new track must either:
  - link to an existing `Work`
  - or create a new `Work` from that track
- `Work Manager` remains the parent-governance, ownership, contribution, and linked-track management surface
- `Catalog` remains operational inventory, not the primary musical creation start

## Add Track Workflow Changes

- restored `Add Track…` as the primary creation action in the shell and action ribbon
- removed the normal user-facing `Create Musical Entry…` start from menus, ribbon defaults, and routing
- kept the docked Add Track surface as the actual working editor, but made governance mandatory inside that flow instead of bouncing out to a separate chooser
- added an explicit in-panel governance mode:
  - `Create New Work from This Track`
  - `Link to Existing Work`
- blocked save when `Link to Existing Work` is selected but no parent work is chosen
- kept child relationship type and optional parent-track selection available for governed child-track cases under an existing work

## Add Album Workflow Changes

- restored `Add Album…` as the primary batch creation action
- removed the assumption that the whole batch must stay in one batch-level governance mode
- made `Add Album` behave as batch `Add Track`
- each populated row now resolves governance individually:
  - link row to existing `Work`
  - or create new `Work` from that row
- rows seeded from `Work Manager -> Add Album to Work` start with that work preselected, but each row can still be changed before save
- new batch saves still cannot create orphan tracks

## Track -> Work Auto-Seeding

When a new Work is created from track entry, the app now seeds shared governance metadata automatically from the track flow instead of opening a second duplicated authoring step.

Current seeded fields:

- `Work.title <- Track.track_title`
- `Work.iswc <- Track.iswc`
- `Work.registration_number <- Track.buma_work_number`
- `Work.profile_name <- current profile`

The same seeded behavior now applies:

- from `Add Track`
- from each `Add Album` row in `create_new_work` mode

This removes the duplicate-entry problem from the same creation flow:

- the user enters the shared concept once in track entry
- the new Work is created from that entered data automatically
- later edits remain independent, so track edits do not silently overwrite Work metadata

## Party-Backed Artist Seeding Fix

Artist identity is now resolved through the Party authority path during track and album creation.

Implemented behavior:

- `Add Track` artist combos are Party-backed
- `Add Album` row artist combos are Party-backed
- if a Party-backed artist is selected, the saved track artist display comes from the canonical Party record
- if raw text matches an existing Party alias or Party-backed name, the canonical Party-backed artist label is used
- if raw text does not match an existing Party, the Party service can still ensure a Party record and resolve the stored artist display from that authority path

This correction prevents loose-text drift where a Party-backed artist was intended.

## Work Manager Role Correction

`Work Manager` remains important, but its role is now explicitly corrected:

- inspect works
- manage work metadata
- manage linked tracks and parent-child relationships
- manage ownership and contribution follow-up
- handle repair and governance maintenance
- launch `Add Track to Work` or `Add Album to Work` for already-known parent contexts

It is no longer framed as the main product start for new musical creation.

## Shell, Help, And Routing Changes

- removed `Create Musical Entry…` from the main shell actions
- `Edit` menu now starts governed creation with:
  - `Add Track…`
  - `Add Album…`
- `View` now exposes `Show Add Track Panel`
- action-ribbon defaults now promote:
  - `Add Track`
  - `Add Album`
  - `Release Browser`
  - `Work Manager`
- help content now describes:
  - `Add Track` as the primary single-item workflow
  - `Add Album` as batch `Add Track`
  - `Work Manager` as governance/management layer
- README copy now reflects the same corrected model

## Track Entry Reuse

The old reused creation surface survives internally as the `Add Track` working editor.

That is acceptable and intentional.

What changed is the conceptual role:

- it is no longer hidden behind a separate chooser workflow
- it is no longer allowed to create floating orphan tracks
- it now owns the mandatory Work-governance decision inline

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `README.md`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/test_dialog_controller_behaviors.py`
- `tests/test_help_content.py`

## Tests Added Or Updated

- shell startup expectations now assert `Add Track…` and `Add Album…` as primary actions
- shell/menu/ribbon expectations now assert `Show Add Track Panel` and the corrected action-ribbon defaults
- Work Manager interaction coverage now asserts:
  - `Add Track to Work`
  - `Create Work`
  - `Add Album to Work`
- Add Track coverage now asserts:
  - missing existing-work selection blocks save in link mode
  - creating a new Work from track entry seeds work title, ISWC, registration number, and canonical Party-backed artist display
- Add Album coverage now asserts:
  - rows seeded from an existing work save governed child tracks
  - empty-work rows auto-create governed parent works
  - mixed row governance is allowed and works correctly in one batch
- help-content coverage now asserts the corrected track-first model
- dialog-controller coverage now removes the retired chooser assumptions and keeps Work Manager create-work behavior covered

## Validation

Validated with:

- `python3 -m py_compile ISRC_manager.py isrc_manager/main_window_shell.py isrc_manager/works/dialogs.py isrc_manager/help_content.py tests/app/_app_shell_support.py tests/app/test_app_shell_editor_surfaces.py tests/app/test_app_shell_workspace_docks.py tests/app/test_app_shell_startup_core.py tests/test_dialog_controller_behaviors.py tests/test_help_content.py`
- `python3 -m unittest tests.test_help_content tests.test_dialog_controller_behaviors`
- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces`
- `python3 -m unittest tests.app.test_app_shell_layout_persistence`
- `python3 -m unittest tests.test_work_and_party_services tests.test_repertoire_status_service`
- `python3 -m unittest tests.test_catalog_workflow_integration tests.integration.test_global_search_relationships`
- `python3 -m unittest tests.test_catalog_read_service tests.test_quality_service tests.test_xml_export_service`

## Risks And Caveats

- the older historical handoffs still describe the superseded Work-Manager-first detour; use this document as the active correction when they conflict
- Add Track -> new Work seeding currently covers the shared fields that already exist cleanly in the Work model; it does not invent speculative composition contributors from a track artist
- Add Album per-row governance is now the active product model; any future attempt to reintroduce whole-batch forced governance rules should be documented deliberately before implementation
- the retired chooser-era codepaths were removed from runtime routing, but further dead-code cleanup can continue opportunistically if more stale references appear

## QA/QC Summary From Central Oversight

Central Oversight signoff:

- the incorrect Work-Manager-first creation assumption has been removed from the active shell
- `Add Track` is again the primary single-item creation start
- `Add Album` is again the primary batch creation start
- new tracks cannot stay orphaned because governance is required inline
- creating a new Work from track entry now reuses shared metadata instead of forcing duplicate entry
- Party-backed artist resolution is explicit in both single-track and batch entry
- `Work Manager` remains strong as a governance surface without pretending to be the main creation start

The app is now in a working state with track-first creation, mandatory Work governance, and no duplicate entry of shared Track/Work metadata as far as the current schema allows.

## Exact Safe Pickup Instructions

Before resuming broader Phase 4 work:

1. read this handoff first
2. treat this correction as the active source of truth when older Phase 3 handoffs conflict
3. resume Phase 4 only from read-side catalog/search/export cleanup, not by revisiting the creation start model again
4. preserve the corrected creation split:
   - `Add Track` / `Add Album` for entry
   - `Work Manager` for governance follow-up

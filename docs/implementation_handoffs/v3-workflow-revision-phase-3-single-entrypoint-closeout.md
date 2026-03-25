# V3 Workflow Revision Phase 3 Single Entrypoint Closeout

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status

This closeout is `completed`.

The app is now in a stable working state with one governed musical creation entry point before broader Phase 4 work continues.

## Purpose

Close the pre-Phase-4 creation-flow consolidation requested after the album-governance decision note.

This handoff records:

- the competing creation paths that were still alive after the earlier Phase 3 slices
- the final unified governed creation workflow now in place
- how the old Track Entry surface survives internally without remaining a competing normal workflow
- how album entry fits into the same governed creation system
- the shell/help cleanup completed before broader Phase 4 read-side work resumes

## Old Competing Creation Paths Found

- `Work Manager` still exposed three parallel creation buttons:
  - `Add`
  - `Add Track to Work`
  - `Add Album to Work`
- the `Edit` menu still presented top-level direct creation-adjacent actions:
  - `Save Track`
  - `Add Album…`
- the docked recording surface still read as a normal creation workspace:
  - title `Track Entry`
  - toggle `Show Track Entry Panel`
  - direct bottom-row `Add Album…`
  - direct new-track save with no parent work context
- the album dialog still read like a peer primary creation route instead of a governed batch-entry surface
- help and README copy still described `Track Entry` / `Add Data` / `Add Album` as normal parallel starts

## Final Unified Creation Workflow

The final user-facing workflow is now:

1. start from `Work Manager` and use `Create Musical Entry…`
2. choose one governed outcome inside the unified decision dialog:
   - `New Work + First Track`
   - `New Work + Governed Album Batch`
   - `Child Track Under Existing Work`
   - `Governed Album Batch Under Existing Work`
   - `Auto-Governed Album Batch (One Work Per Track)`
3. review the preview text before continuing so the parent/child result is explicit
4. continue into the next surface only after that governed choice is made:
   - new-work modes open `WorkEditorDialog` first, then continue automatically
   - single-track modes open the internal `Recording Editor` already scoped to the parent work
   - album modes open `Album Batch Entry` with either a locked shared parent or the explicit per-track auto-govern fallback

There is no longer a separate normal user workflow where a brand-new track can be created directly from the old floating Add Track surface.

## What Changed

- `Work Manager` now exposes one creation CTA: `Create Musical Entry…`
- added `GovernedMusicalEntryDialog` plus `GovernedMusicalEntryPlan` in [`isrc_manager/works/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/works/dialogs.py)
- added `App.open_musical_entry_workflow()` in [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- new-work creation now continues directly into first-track or album-batch follow-up without falling back to the older yes/no prompt workflow when launched from the unified entrypoint
- existing-work child-track creation now routes through the same unified flow and can preselect governed child relationship before the recording editor opens
- existing-work album-batch creation now routes through the same unified flow and can preselect shared batch relationship before `Album Batch Entry` opens
- explicit auto-governed album fallback now routes through the same unified flow instead of standing as a separate primary album start
- saving from the docked recording editor without a bound work context no longer creates a floating track; it now redirects the user back into `Create Musical Entry`
- `Reset Form` no longer clears the active work-governance context; the escape hatch is now `Return to Work Manager`

## Track Entry Reuse

`Track Entry` was not kept as a competing conceptual workflow.

It was renamed and reframed as `Recording Editor`.

Its role is now:

- internal host for governed child-track entry launched from the unified flow
- hidden-by-default helper surface that can still be shown from `View`
- operational repair / administrative follow-up surface

What it no longer is:

- the normal way to start a brand-new musical entry
- a floating track-first workflow
- a peer concept to `Work Manager`

## Album Integration Model

Album entry is now explicitly part of the same governed creation system.

The allowed album modes remain aligned with the reconciled decision note:

- `shared-parent mode`
  - chosen from the unified flow under an existing parent work, or after creating a new work first
  - the dialog opens locked to that work
  - every saved track inherits the same parent work and shared relationship type
- `auto-governed fallback mode`
  - chosen explicitly from the unified flow
  - the dialog opens with no shared parent work
  - every saved track creates its own parent work
  - relationship type is fixed by behavior to `original`

What was tightened in the album surface:

- the dialog is now titled `Album Batch Entry` / `Album Batch Entry for Work`
- fallback wording no longer implies “standalone” creation
- the relationship selector is disabled when no shared parent work is selected
- no mixed governance mode is allowed within one album save

## Shell Cleanup Completed

- added a global `Create Musical Entry…` action that routes into the unified flow
- removed `Add Album…` from the top-level `Edit` menu
- removed `Save Track` from the top-level `Edit` menu as a normal creation affordance
- moved the dock toggle out of `Catalog > Workspace` and renamed it `Show Recording Editor` under `View`
- renamed the dock title and copy from `Track Entry` to `Recording Editor`
- replaced the work-context escape button with `Return to Work Manager`
- removed the bottom-row `Add Album…` button from the recording editor
- updated action-ribbon inventory and defaults so the visible promoted creation concept is `Create Musical Entry`
- updated help and README wording to present:
  - `Work Manager` as the governed start
  - `Recording Editor` as the reused internal recording surface
  - `Album Batch Entry` as the governed batch-entry surface

## Source Of Truth Files And Surfaces

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/main_window_shell.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/main_window_shell.py)
- [`isrc_manager/works/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/works/dialogs.py)
- [`isrc_manager/help_content.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/help_content.py)
- [`README.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/README.md)
- [`docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md)

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/works/dialogs.py`
- `isrc_manager/help_content.py`
- `README.md`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`
- `tests/app/test_app_shell_workspace_docks.py`
- `tests/test_dialog_controller_behaviors.py`
- `tests/test_help_content.py`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-3-single-entrypoint-closeout.md`

## Tests Added Or Updated

- updated shell coverage so `Work Manager` now launches the unified creation workflow instead of old parallel buttons
- updated shell coverage for:
  - new work + first track through the unified flow
  - existing work + governed child variant through the unified flow
  - existing work + governed album batch through the unified flow
  - explicit auto-governed album fallback through the unified flow
  - redirecting no-context recording saves back into the governed creation workflow
- updated startup/menu coverage so the shell no longer presents `Track Entry` / `Add Album…` as primary creation starts
- updated dialog-controller coverage for the unified creation launcher and its validation behavior
- updated help-content coverage to pin Work-Manager-first governance wording
- retained and revalidated existing album-governance dialog coverage

## Validation

- `python3 -m unittest tests.app.test_app_shell_workspace_docks`
- `python3 -m unittest tests.app.test_app_shell_editor_surfaces tests.app.test_app_shell_startup_core tests.app.test_app_shell_layout_persistence tests.test_dialog_controller_behaviors tests.test_help_content`

Result:

- `77` tests passed

## Risks And Caveats

- the unified creation system is one integrated workflow, but it is still a staged workflow rather than one monolithic wizard:
  - decision dialog
  - work editor when needed
  - recording editor or album batch entry after that
- the `Recording Editor` still exists as a visible helper surface when the user explicitly shows it from `View`; its safety now depends on the no-context redirect rather than full removal
- lineage-rich batch derivative authoring still does not capture per-track `parent_track_id` in album mode; one-by-one child-track creation remains the right path for version/remix trees
- auto-created fallback works in album mode still seed only lightweight work metadata
- this closeout intentionally does not broaden Phase 4 read-side cleanup, catalog projection work, or legacy-license deletion

## Workers Used And Workers Closed

- Workers used:
  - `Zeno`
  - `Tesla`
  - `Bohr`
  - `Archimedes`
  - `Erdos`
  - `Boole`
- Workers closed:
  - `Zeno`
  - `Tesla`
  - `Bohr`
  - `Archimedes`
  - `Erdos`
  - `Boole`

## QA/QC Summary From Central Oversight

Central Oversight sign-off:

- the app no longer exposes a separate standalone Add Track workflow as a normal product path
- `Work Manager` is now the one governed musical creation entrypoint
- album creation is absorbed into that same governed system instead of surviving as a separate primary mental model
- the old docked editor remains available only as a reused internal recording surface
- menus, ribbon, help, and README now point to the same intended workflow
- the app is stable and validated at this boundary

Explicit sign-off statement:

The app is now in a working state with one governed musical creation entry point before broader Phase 4 continuation.

## Exact Safe Pickup Instructions

Next safe continuation:

1. read the masterplan, the main Phase 3 handoff, the album-governance decision note, and this closeout handoff in that order
2. treat this closeout as the authoritative boundary that Phase 4 had to satisfy before broader read-side cleanup could continue
3. begin the next Phase 4 slice from read-side authority cleanup only:
   - catalog projections
   - search/export read paths
   - operational edit/bulk-edit cleanup
4. keep `Catalog` as the operational inventory and execution layer, not a new creation surface
5. do not reopen parallel musical creation routes while doing Phase 4 cleanup

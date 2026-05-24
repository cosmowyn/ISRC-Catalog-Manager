# Pre-Implementation Plan Hardening Handoff

Completion timestamp: 2026-05-24 20:32:38 CEST
Status: Completed

## Scope

This was a planning-document remediation pass only. No application implementation was performed, no Plan 1 or Plan 2 phase execution was started, and no runtime behavior was changed.

## Files Inspected

- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-0 - Packaging and Compatibility Gate.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-1 - Logging and Prompt Helpers.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-2 - Audio Visualizer Extraction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-3 - Media Preview Dialogs.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-4 - Live Catalog Manager Panels.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-5 - Dead Catalog Dialog Audit.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-6 - Legacy License UI Decision Gate.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-7 - Settings Dialog Whole Move.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-8 - Settings Dialog Internal Health Pass.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-9 - Album and Track Editor Host Seams.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-10 - Album Dialog Extraction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-11 - Track Editor Final Seam Check.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 1/P1-Phase-12 - Edit Dialog Extraction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-13 - Foreground Service Container.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-14 - Profile, Storage, and Session Controller.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-15 - Diagnostics Report and Controller.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-16 - Theme, Settings, History Retention, and App Sound Controllers.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-17 - Layout, Workspace Shell, and Action Ribbon Controllers.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-18 - Catalog Workflow Controller.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-19 - Feature Workflow Controllers.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-20 - Lean App Move.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Phase 2/P2-Phase-21 - Final Compatibility Cleanup.md`
- `ISRC_manager.py` was inspected for planning alignment only. It was not modified.

## Files Modified

- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 1 - Non-App Class Extraction and Compatibility Stabilization.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Engineering Plan 2 - App Decomposition and Final Entry-Facade Reduction.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Follow-Up_Engineering_Plan_Architecture_Enforcement.md`
- All Plan 1 phase prompt markdown files.
- All Plan 2 phase prompt markdown files.

## Files Added

- `docs/change control/Change - ISRC_manager De-Monolithization/compatibility_inventory.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/architecture_metrics.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/phase execution handoffs/Pre-Implementation Plan Hardening handoff.md`
- `docs/change control/Change - ISRC_manager De-Monolithization/Milestones.md`

## Planning Prompt Title Alignments

The following phase prompt filenames were aligned with the current engineering plan titles:

- `P1-Phase-2 - Waveform Extraction.md` -> `P1-Phase-2 - Audio Visualizer Extraction.md`
- `P1-Phase-9 - Album Editor Host Seam.md` -> `P1-Phase-9 - Album and Track Editor Host Seams.md`
- `P1-Phase-10 - Album Entry Extraction.md` -> `P1-Phase-10 - Album Dialog Extraction.md`
- `P1-Phase-11 - Track Editor Host Seam.md` -> `P1-Phase-11 - Track Editor Final Seam Check.md`
- `P2-Phase-14 - Profile and Session Controller.md` -> `P2-Phase-14 - Profile, Storage, and Session Controller.md`
- `P2-Phase-16 - Theme, Settings, and History Retention Controllers.md` -> `P2-Phase-16 - Theme, Settings, History Retention, and App Sound Controllers.md`
- `P2-Phase-17 - Layout and Action Ribbon Controllers.md` -> `P2-Phase-17 - Layout, Workspace Shell, and Action Ribbon Controllers.md`

## Planning Recommendations Implemented

- Made `Follow-Up_Engineering_Plan_Architecture_Enforcement.md` a mandatory governance layer for Plan 1 and Plan 2 instead of an optional or parallel cleanup track.
- Added mandatory phase-gate language requiring the follow-up enforcement plan to be applied throughout the campaign.
- Added the requirement that the campaign is incomplete until the final architecture completion gate passes.
- Made `compatibility_inventory.md` mandatory from Plan 1 Phase 0 onward.
- Added compatibility inventory requirements for alias source, alias target, owning phase, dependent runtime callers, dependent tests, deprecation warning status, migration target path, planned removal phase, current status, notes, and exception references.
- Added the rule that no compatibility alias may be added unless it is recorded in the inventory.
- Added the rule that no compatibility alias may remain without a planned removal phase.
- Added the rule that every phase handoff and milestone update must state inventory status.
- Made every compatibility alias explicitly temporary and deprecated, or require a documented reason why warning is not technically safe yet.
- Added compatibility alias requirements to Plan 1 governing rules, Plan 1 Phase 0, Plan 1 handoff rules, Plan 2 Phase 21, the follow-up plan, and phase prompt handoff requirements.
- Added a mandatory Plan 1 Completion Gate after Phase 12.
- Added Plan 1 Completion Gate checks for no remaining non-`App` local UI/helper definitions in `ISRC_manager.py`, moved imports, deleted legacy UI decisions, host protocol documentation, current compatibility inventory, deprecated root aliases with removal phases, no extracted module importing `App`, no new circular imports, package parity, compile/import sanity, and focused smoke checks.
- Added a mandatory Plan 2 Entry Gate before Phase 13.
- Added Plan 2 Entry Gate requirements for Plan 1 gate pass, final handoff, current compatibility inventory, root import baseline, alias baseline, import-cycle baseline, module LOC baseline, `ISRC_manager.py` LOC baseline, `App` LOC baseline, tests still using root imports, package parity status, and no Plan 2 start while Plan 1 extraction remains incomplete.
- Hardened Plan 2 Phase 21 into a zero-debt cleanup gate.
- Required Phase 21 to finish with zero compatibility aliases, zero deprecated root imports, zero root re-exports except startup bootstrap imports, zero temporary migration wrappers, zero legacy test imports from `ISRC_manager`, removed-only or empty compatibility inventory, CI/architecture validation rules specified, and `ISRC_manager.py` reduced to bootstrap imports, `main()`, and startup glue.
- Clarified that any API intended to remain public must move to a proper package-level public module rather than remain as a root compatibility alias.
- Split Plan 2 Phase 19 into named subphases 19A through 19I.
- Added the rule that only one Phase 19 subphase may run per Codex run unless a later planning document explicitly authorizes a combined run.
- Added focused validation, architecture metrics, compatibility inventory, and anti-catch-all requirements for every Phase 19 subphase.
- Strengthened Plan 1 Phase 5 and Phase 6 dead-code deletion audits.
- Required deletion audits to cover runtime call paths, tests, documentation/examples, root compatibility imports, command/action registries, menu/ribbon/workspace registrations, string-based dynamic lookups, persisted layout/action references, database migration references where applicable, and external script/tool references.
- Added the rule that deletion is allowed only when the audit confirms no live or compatibility need.
- Added the rule that code may be quarantined only when compatibility need exists and quarantine is safe and justified.
- Added media architecture anti-monolith gates to Plan 1 Phase 3 and Plan 2 Phase 19D.
- Required media responsibilities to remain separated into visualization, preparation/preload, playback, and export.
- Required reuse of waveform cache, equalizer, equalizer player, and bookmarks infrastructure instead of duplication.
- Required media preview extraction not to become a new media platform monolith.
- Required Plan 2 media controller extraction not to pull preview dialogs back into controller modules.
- Clarified the Plan 1 Phase 8 settings boundary.
- Allowed Phase 8 UI tab/panel splits, local dialog size reduction, and UI-only helper isolation.
- Prohibited broad settings architecture redesign, permanent settings workflow ownership, controller extraction belonging to Plan 2 Phase 16, and `App` responsibility decomposition in Phase 8.
- Added architecture metrics tracking requirements to the follow-up enforcement plan and Plan 2 gates.
- Created `architecture_metrics.md` as a planning placeholder for gate records.
- Updated all Plan 1 phase prompt handoff expectations for compatibility inventory status, root alias changes, deprecated wrapper changes, architecture boundary observations, package parity, import-cycle risk, module-size risk, no permanent migration glue, and new alias target/deprecation/removal/inventory confirmation.
- Updated Plan 2 prompts to reference the mandatory architecture enforcement plan and common handoff requirements.

## Recommendations Not Implemented

- No CI validation rules were implemented in workflows. They were documented as future implementation requirements because this pass was documentation-only.
- No metrics scripts were implemented. `architecture_metrics.md` was created as a planning placeholder, and live metrics are to be recorded during the required gates.
- No compatibility aliases were added, deprecated, migrated, or removed. Those changes belong to execution phases.
- No Python modules, tests, package files, build files, or source imports were changed.
- No Plan 1 or Plan 2 implementation work was started.

## Source Implementation Confirmation

- No application source code was changed.
- No tests were changed.
- No CI workflow files were changed.
- No build or packaging configuration files were changed.
- No class, function, or module moves were performed.
- No runtime compatibility aliases were implemented.
- No Plan 1 phase execution was started.
- No Plan 2 phase execution was started.

## Consistency Checks Performed

- Confirmed Plan 1 now requires `compatibility_inventory.md` from Phase 0.
- Confirmed Plan 1 includes a mandatory Completion Gate after Phase 12.
- Confirmed Plan 2 includes a mandatory Entry Gate before Phase 13.
- Confirmed Plan 2 Phase 21 uses hard zero-debt completion language.
- Confirmed Plan 2 Phase 19 is split into named subphases 19A through 19I.
- Confirmed Phase 5 and Phase 6 include stronger dead-code audit criteria.
- Confirmed Phase 3 and Phase 19D include media anti-monolith gates.
- Confirmed Phase 8 boundaries do not overlap with Plan 2 Phase 16 controller work.
- Confirmed the follow-up enforcement plan is mandatory governance.
- Confirmed affected phase prompts include the expanded handoff expectations.
- Confirmed documentation updates describe future source, CI, and test requirements without implementing them.

## Remaining Risks Before Starting P1 Phase 0

- Phase 0 still needs to populate the initial compatibility inventory with actual alias data if any aliases are introduced or discovered.
- Phase 0 still needs to record live architecture metrics in `architecture_metrics.md`.
- Architecture validation scripts and CI gates are specified but not yet implemented.
- Current source metrics and root-import baselines have not been generated by this planning pass.
- Any existing unrelated working-tree changes outside the de-monolithization planning area must be kept separate from Plan 1 execution.

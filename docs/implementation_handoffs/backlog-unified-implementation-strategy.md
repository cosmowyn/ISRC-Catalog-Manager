# Backlog Unified Implementation Strategy

Current product version: `2.0.0`
Date: 2026-03-22

## Status

This document uses the live repository as the source of truth. It was created from a full repo inspection plus focused analysis of UI, services, responsiveness, storage/history, tests, and handoff conventions.

Implementation is in progress after the planning pass. Wave 1 and Wave 2 are complete in this pass, with focused regression coverage run locally. Wave 3 through Wave 5 remain open and should continue in the original order.

## Source Of Truth

- User backlog dated 2026-03-22
- Current repository code, especially `ISRC_manager.py`
- Prior handoffs:
  - [reference-system-followup.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/reference-system-followup.md)
  - [storage-cleanup-and-data-layout-handoff.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md)
  - [storage-migration-reliability-fix.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-migration-reliability-fix.md)
  - [qsplashscreen-startup.md](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/qsplashscreen-startup.md)
- Key code surfaces:
  - `ISRC_manager.py`
  - `isrc_manager/exchange/*`
  - `isrc_manager/history/*`
  - `isrc_manager/contracts/*`
  - `isrc_manager/tasks/*`
  - `isrc_manager/ui_common.py`
  - `isrc_manager/main_window_shell.py`

## Full Backlog Classification

### 1. Critical Bug Fixes

1. Export filenames replace leading letters with `_`
- Current state: export/save helpers in `ISRC_manager.py` use a broken local filename sanitizer; managed storage uses a separate helper in `file_storage.py`.
- Why it matters: exported filenames are visibly corrupted and the bug affects multiple export entry points.
- Primary code surfaces: `ISRC_manager.py`, `isrc_manager/file_storage.py`
- Dependency class: shared export scaffold
- Risk level: low if kept export-only
- Required tests: export basename regression coverage

2. Track save crashes with `propagated_field_labels` `NameError`
- Current state: single-track edit only defines `propagated_field_labels` inside one branch but later reads it unconditionally.
- Why it matters: saving a track can fail on a core editing workflow.
- Primary code surfaces: `ISRC_manager.py`
- Dependency class: shared propagation summary cleanup
- Risk level: low
- Required tests: editor save without propagation, editor save with propagation

### 2. Low-Risk UX Fixes

3. Profiles ribbon should be toggleable
- Current state: profiles toolbar exists but has no persisted visibility toggle like other workspace panels.
- Why it matters: users cannot reclaim vertical space consistently.
- Primary code surfaces: `isrc_manager/main_window_shell.py`, `ISRC_manager.py`
- Dependency class: view preference helper
- Risk level: low
- Required tests: app-shell visibility persistence

4. First launch should optionally offer opening settings
- Current state: first-run initialization seeds settings only; no post-ready prompt exists.
- Why it matters: onboarding is opaque and users miss configuration entry points.
- Primary code surfaces: `isrc_manager/settings.py`, `ISRC_manager.py`
- Dependency class: startup preference helper
- Risk level: low
- Required tests: first-run one-shot prompt behavior

5. Contract manager top button group overlaps vertically
- Current state: contract browser still uses `_create_action_button_grid()` instead of the denser cluster helper already used elsewhere.
- Why it matters: layout overlap degrades a catalog management surface.
- Primary code surfaces: `isrc_manager/contracts/dialogs.py`, `isrc_manager/ui_common.py`
- Dependency class: action-row cluster reuse
- Risk level: low
- Required tests: dialog smoke/layout assertions

6. Export menu labels and categories are unclear
- Current state: XML export, exchange export, and repertoire exchange are grouped inconsistently across menus and ribbon metadata.
- Why it matters: export workflows are harder to discover and interpret.
- Primary code surfaces: `isrc_manager/main_window_shell.py`, `ISRC_manager.py`
- Dependency class: export action naming/grouping
- Risk level: low
- Required tests: menu/ribbon label grouping coverage

### 3. Medium-Risk Workflow Improvements

7. Import dialog remember choice plus reset entry
- Current state: only mapping presets persist; run-mode and match options do not.
- Why it matters: repeated imports are noisy and inconsistent.
- Primary code surfaces: `isrc_manager/exchange/dialogs.py`, `isrc_manager/exchange/models.py`, `ISRC_manager.py`, `isrc_manager/main_window_shell.py`
- Dependency class: exchange import preference store
- Risk level: medium
- Required tests: dialog persistence/reset behavior

8. Import option to skip a field
- Current state: blank mapping behaves like an implicit skip for mapped formats, but there is no explicit first-class skip option and no shared skip behavior for direct JSON/package flows.
- Why it matters: users need a deliberate safe way to ignore fields instead of mapping or creating them.
- Primary code surfaces: `isrc_manager/exchange/dialogs.py`, `isrc_manager/exchange/models.py`, `isrc_manager/exchange/service.py`
- Dependency class: exchange import preference store
- Risk level: medium
- Required tests: skip-target import coverage across formats

9. Bulk export of stored blobs from the focused column
- Current state: table context menu supports only single-cell export.
- Why it matters: exporting stored media at scale is tedious and error-prone.
- Primary code surfaces: `ISRC_manager.py`, standard/custom blob read services
- Dependency class: media export resolver
- Risk level: medium
- Required tests: context-menu bulk export plan and filename behavior

10. Album art export should use album title, not track title
- Current state: standard media export defaults to track title for every media type.
- Why it matters: shared album art exports are mislabeled and confusing.
- Primary code surfaces: `ISRC_manager.py`, release/album context helpers
- Dependency class: media export resolver
- Risk level: low-to-medium
- Required tests: album-art basename coverage

11. Diagnostics loading feels hung
- Current state: diagnostics dialog builds the full report synchronously in the dialog constructor/refresh path.
- Why it matters: the app appears frozen during a heavy integrity/storage scan.
- Primary code surfaces: `isrc_manager/app_dialogs.py`, `ISRC_manager.py`, `isrc_manager/tasks/*`
- Dependency class: async loading adapter
- Risk level: medium
- Required tests: async load, refresh, and repair callback coverage

### 4. High-Risk Architecture Or Service Changes

12. Theme apply after save still freezes the UI
- Current state: saving settings applies palette/font/stylesheet immediately on the main thread.
- Why it matters: users experience blocking during a core preferences workflow.
- Primary code surfaces: `ISRC_manager.py`, `isrc_manager/theme_builder.py`
- Dependency class: staged theme-prep/apply pipeline
- Risk level: high because Qt UI mutation must remain on the UI thread
- Required tests: theme staging and deterministic completion

13. Bulk audio upload with filename matching and fast artist assignment
- Current state: no dedicated bulk-audio attach/import workflow exists.
- Why it matters: this is a large missing workflow and needs both matching and bulk metadata application.
- Primary code surfaces: new dialog/service, `isrc_manager/tags/service.py`, `isrc_manager/services/tracks.py`, `isrc_manager/exchange/service.py`, `ISRC_manager.py`
- Dependency class: bulk audio attach service
- Risk level: high
- Required tests: matching, ambiguity resolution, batch attach/history

14. Contract obligations should use proper UI elements
- Current state: obligations are edited as a pipe-delimited text block even though the service and models already support structured obligation records.
- Why it matters: the current UI is unclear and easy to corrupt.
- Primary code surfaces: `isrc_manager/contracts/dialogs.py`, `isrc_manager/contracts/models.py`, `isrc_manager/contracts/service.py`
- Dependency class: structured contract row editor
- Risk level: medium-to-high
- Required tests: dialog payload round-trip

15. Legacy custom/default column collision repair
- Current state: same-name field type conflicts still fail import flows and existing promoted-field migration logic is migration-only.
- Why it matters: imports can fail and legacy data remains stranded without a repair path.
- Primary code surfaces: `isrc_manager/exchange/service.py`, `isrc_manager/services/custom_fields.py`, `isrc_manager/services/schema.py`, diagnostics
- Dependency class: field-resolution helper and repair service
- Risk level: high
- Required tests: safe merge preview, import fallback, diagnostics repair coverage

### 5. History / Storage Lifecycle Features

16. Snapshot and history anti-disk-spam controls
- Current state: cleanup UI exists but there is no profile-level retention/budget policy or automatic rolling enforcement.
- Why it matters: history growth is unbounded and can spam disk.
- Primary code surfaces: `isrc_manager/history/cleanup.py`, `isrc_manager/history/manager.py`, `isrc_manager/history/session_manager.py`, settings services, `ISRC_manager.py`
- Dependency class: history policy engine
- Risk level: high
- Required tests: budget enforcement, prompt/refusal behavior, artifact protection, root-safety invariants

## Dependency Map

### Shared Data / Schema / Settings Dependencies

- Export filename behavior spans local picker export and managed-storage/package naming.  
Implication: add an export-only basename helper instead of changing managed-storage sanitization globally.

- Exchange import behavior is split across dialog options, direct service import, and custom-field creation.  
Implication: persistence, skip-targets, and same-name field resolution should land together.

- History policy belongs in existing profile-scoped settings services and cleanup inventory.  
Implication: do not invent a second retention system.

- Legacy field repair must preserve promoted/default-column semantics already encoded in schema migration.  
Implication: extract reusable merge logic from existing promoted-field reconciliation instead of duplicating it.

### UI / Service / Persistence Coupling

- Diagnostics uses synchronous UI calls into database/storage inspection and repair logic.  
Implication: convert to async callbacks without changing diagnostic report wire shapes.

- Theme saving and theme application are coupled today, but only theme computation can move off-thread.  
Implication: stage compute/prep in the worker and keep final Qt apply on the main thread.

- Contract obligations already serialize as structured payloads even though the UI is plain text.  
Implication: replace only the editor surface and preserve `ContractPayload.obligations`.

- Bulk audio attach will need exact/normalized matching and batched artist resolution.  
Implication: extract reusable matcher logic instead of re-implementing one-off heuristics inside a dialog.

### Ordering Constraints Between Backlog Clusters

- Export helper work must land before bulk blob export, album-art naming, and export menu cleanup.  
Implication: W1 export scaffold before W2 export conversions.

- Import preference storage and field-resolution logic should land before skip targets and legacy import conflict handling.  
Implication: W2 groups 4, 8, and the defensive half of 15.

- Diagnostics async scaffold should land before staged theme apply, because the same background-task conventions are reused.  
Implication: W3 diagnostics first, then theme-save/apply.

- History/storage hardening must trail new managed-media workflows.  
Implication: W5 closes snapshot-coverage and retention after W2/W4 media features are defined.

## Shared Scaffolding

### UI Scaffolding

- Async loading adapter
  - Used by: diagnostics loading and repairs, staged theme save/apply
  - Prevents: bespoke progress plumbing and unsafe thread usage
  - Done means: bundle-task backed loader callbacks, inline state, deterministic success/error handling

- View/startup preference helper
  - Used by: profiles toolbar visibility, first-launch settings prompt
  - Prevents: one-off `QSettings` keys and duplicated startup checks
  - Done means: persisted toggle state plus one-shot prompt sentinel

- Structured contract row editor
  - Used by: obligations editor
  - Prevents: more text DSL parsing and payload drift
  - Done means: add/edit/remove rows while preserving existing payload semantics

### Service / Model Scaffolding

- Export media resolver
  - Used by: export filename bug, focused-column bulk export, album-art naming, export regrouping
  - Prevents: repeated basename logic in context menus and file exporters
  - Done means: owner-aware basename resolution and track/custom media export planning from one place

- Exchange import preference and field-resolution helper
  - Used by: remember-choice, explicit skip, legacy same-name field reuse
  - Prevents: ad hoc dialog-only state and blind `text` field creation
  - Done means: persisted options, explicit skip targets, safe reuse of existing matching field defs

- Bulk audio attach service
  - Used by: bulk audio upload/matching/artist assignment
  - Prevents: private dialog-side matching logic and row-by-row attachment code
  - Done means: inspect files, produce match candidates, stage user decisions, apply in one history-wrapped mutation

- History policy engine
  - Used by: storage budget enforcement and the repair half of legacy-media safety work
  - Prevents: cleanup logic scattering across timers and dialogs
  - Done means: inspect, prune, prompt, and respect manual artifact protections

### Persistence / Migration Scaffolding

- Promoted default-field repair service
  - Used by: same-name field conflict repair and diagnostics repair entry
  - Prevents: import-time crashes with no guided repair
  - Done means: preview, merge, validate, drop redundant custom field only after preserved data is confirmed

## Execution Waves

### Wave 0. Strategy Handoff

Goal:
- create this document before code edits and keep it current

Included:
- unified backlog normalization
- explicit dependency order
- live `implemented`, `remaining`, and `tests` sections

Exit criteria:
- document exists in the repo
- later waves can update it without redoing analysis

### Wave 1. Foundations And Unblockers

Goal:
- land low-risk fixes that remove immediate regressions and establish reusable preference/layout seams

Included backlog items:
- export-only basename helper
- `propagated_field_labels` fix
- profiles ribbon toggle
- first-launch settings prompt
- contract browser action-row cluster

Likely files:
- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/contracts/dialogs.py`
- tests in `tests/app/*` and `tests/catalog/*`

Exit criteria:
- no track-save crash in the non-propagation path
- profiles toolbar visibility persists
- first-run prompt is one-shot and optional
- contract browser action row uses cluster layout

### Wave 2. Shared Import / Export Conversions

Goal:
- land the shared exchange/export scaffolding before broader workflow additions

Included backlog items:
- remember import choice
- reset import choice menu entry
- explicit skip-field support
- defensive same-name field reuse during import
- focused-column bulk blob/media export
- owner-aware album-art naming
- export menu/ribbon regrouping

Likely files:
- `isrc_manager/exchange/dialogs.py`
- `isrc_manager/exchange/models.py`
- `isrc_manager/exchange/service.py`
- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`

Exit criteria:
- per-format import options persist and can be reset
- skipped targets are excluded safely across supported import modes
- focused-column export works for selected rows only
- album-art export names derive from album context

### Wave 3. Responsiveness And Loading

Goal:
- make heavy diagnostics/theme flows visibly busy and deterministic without unsafe cross-thread UI changes

Included backlog items:
- async diagnostics load
- async diagnostics repairs
- staged theme save/apply

Likely files:
- `isrc_manager/app_dialogs.py`
- `ISRC_manager.py`
- `isrc_manager/tasks/*`
- theme-related tests

Exit criteria:
- diagnostics dialog no longer blocks on open/refresh
- repair actions run through background bundle tasks
- theme save shows progress while final apply stays on the UI thread

### Wave 4. New Workflow Surfaces

Goal:
- add the two new user-facing workflows that need fresh shared UI/service scaffolding

Included backlog items:
- bulk attach audio files
- structured contract obligations editor

Likely files:
- new audio attach service/dialog
- `ISRC_manager.py`
- `isrc_manager/contracts/dialogs.py`
- `isrc_manager/contracts/models.py`

Exit criteria:
- bulk audio import can inspect files, match to tracks, assign artists, and attach safely
- obligations edit UI round-trips existing payload fields without DSL parsing

### Wave 5. Repair And Storage Hardening

Goal:
- harden long-lived repair and retention behavior after media/import workflows are in place

Included backlog items:
- diagnostics-driven merge repair for legacy custom/default columns
- history storage budget and retention policy
- snapshot coverage extension for managed roots touched by new workflows

Likely files:
- `isrc_manager/history/*`
- `isrc_manager/services/settings_reads.py`
- `isrc_manager/services/settings_mutations.py`
- `isrc_manager/services/schema.py`
- diagnostics surfaces

Exit criteria:
- field collision repair preserves data and removes redundant legacy fields safely
- history budget policy prunes only eligible auto-generated artifacts
- manual artifacts stay protected by default
- snapshot coverage includes the managed roots required for new media workflows

## Risks And Mitigations

### 1. Export / Naming Drift

- Risk: fixing export names could accidentally change managed-storage naming semantics
- Mitigation: keep a distinct export-only helper and leave `sanitize_filename()` behavior unchanged
- Early warning: managed-file path tests or package fixture names change unexpectedly

### 2. Import Data Loss Or Silent Coercion

- Risk: skip logic or same-name reuse could silently drop or coerce fields
- Mitigation: explicit `Skip` target, no silent type coercion, reuse only when name/type already match
- Early warning: import reports stop listing unknown/conflicting fields or custom-field tests begin passing with missing data

### 3. Qt Thread-Safety Regressions

- Risk: moving diagnostics/theme work off-thread could mutate Qt objects from worker threads
- Mitigation: worker tasks return pure data only; all dialogs, message boxes, palettes, and stylesheets stay on the main thread
- Early warning: flaky UI tests, random crashes, or object-thread affinity warnings

### 4. Workflow Mismatch In Bulk Audio Attach

- Risk: filename heuristics over-match or incorrect artist assignment mutates many tracks
- Mitigation: exact/normalized title heuristics first, explicit ambiguity review, one final history-wrapped apply
- Early warning: ambiguous-match counts are high or artist assignment touches unintended rows

### 5. Over-Pruning History Or Undermining Restore Safety

- Risk: automatic cleanup deletes trusted artifacts or misses managed roots needed for restore
- Mitigation: protect manual artifacts by default, prune only completed auto-generated artifacts, prompt when only user-owned artifacts remain, extend snapshot coverage first
- Early warning: restore tests fail or cleanup previews mark manual artifacts as silently eligible

## Implemented Work In This Pass

### Strategy / Coordination

- Completed the full backlog classification, dependency mapping, shared scaffold mapping, and wave sequencing before code edits.
- Created this handoff as the live source of truth for the unified backlog.

### Wave 1 Completed

- Added `sanitize_export_basename()` in `isrc_manager/file_storage.py` and routed export-only filename generation through it without changing managed-storage sanitization semantics.
- Fixed the single-track save `propagated_field_labels` crash in `ISRC_manager.py`.
- Added a persisted `Show Profiles Ribbon` view action and applied/saved the toolbar visibility preference.
- Added the one-shot first-launch prompt that offers opening Application Settings while keeping defaults when skipped.
- Switched the contract browser action row to `_create_action_button_cluster()` to remove the overlapping top-button layout.

### Wave 2 Completed

- Added per-format exchange import preference persistence in `ExchangeImportDialog`, including a `Remember these ... import choices` checkbox.
- Added `Reset Saved Import Choices…` to the `File > Import Exchange` menu and wired it to clear saved exchange import preferences.
- Added explicit skip-target support in the exchange dialog and extended `ExchangeImportOptions` with `skip_targets`.
- Routed JSON and ZIP package imports through the same mapping pipeline as CSV/XLSX so skip/mapping behavior is shared across exchange formats.
- Changed exchange import custom-field resolution to reuse existing same-name active custom fields instead of blindly attempting to create `text` fields.
- Added focused-column bulk media export scaffolding in `ISRC_manager.py` and exposed it through the table media export path.
- Changed album-art export basenames to use the linked album title when available.
- Renamed and regrouped the File menu export surfaces and related ribbon labels so XML catalog export, exchange data export, and contracts/rights exchange are clearer.

## Remaining Work

### Next Wave To Start

- Wave 3. Responsiveness and loading
  - async diagnostics loading
  - diagnostics repair task wiring
  - staged theme save/apply with UI-thread-safe final mutation

### Still Open After This Pass

- Wave 3. Responsiveness and loading
- Wave 4. Bulk audio attach workflow and structured obligations editor
- Wave 5. Legacy-field repair flow and history/storage hardening

### Important Continuation Notes

- Wave 2 now provides the shared exchange/export scaffolding that later waves should build on instead of replacing:
  - saved exchange import preferences
  - explicit skip-target dialog behavior
  - shared mapping across CSV/XLSX/JSON/package imports
  - same-name custom-field reuse during import
  - shared media export basename and focused-column export helpers
- The legacy custom/default column merge repair is still not implemented. Only the defensive import-side reuse path is complete.
- History storage budgeting, retention controls, and snapshot-coverage expansion are still untouched in code.

## Tests

### Existing Coverage That Must Stay Green

- `tests/app/test_app_shell_startup_core.py`
- `tests/app/test_app_shell_layout_persistence.py`
- `tests/catalog/test_contract_dialogs.py`
- `tests/test_exchange_dialogs.py`
- `tests/exchange/test_exchange_csv_import.py`
- `tests/exchange/test_exchange_json.py`
- `tests/exchange/test_exchange_package.py`
- `tests/test_task_manager.py`
- `tests/test_background_app_services.py`
- `tests/test_history_cleanup_service.py`
- `tests/history/test_history_settings.py`
- `tests/test_theme_builder.py`

### Planned Test Additions Or Updates

- new `tests/test_export_filename_helpers.py`
- app-shell coverage for profiles toolbar visibility and first-run prompt
- exchange dialog/service coverage for remember/reset/skip/field reuse
- diagnostics async load/repair coverage
- bulk audio attach workflow coverage
- contract obligations structured-editor coverage
- history budget and merge-repair coverage

### Added / Updated In This Pass

- Added `tests/test_export_filename_helpers.py`
- Updated `tests/app/_app_shell_support.py`
- Updated `tests/app/test_app_shell_startup_core.py`
- Updated `tests/catalog/_contract_rights_asset_support.py`
- Updated `tests/catalog/test_contract_dialogs.py`
- Updated `tests/test_exchange_dialogs.py`
- Updated `tests/exchange/_support.py`
- Updated `tests/exchange/test_exchange_custom_fields.py`
- Updated `tests/exchange/test_exchange_json.py`
- Updated `tests/exchange/test_exchange_package.py`
- Updated `tests/test_migration_integration.py`

### Validated In This Pass

- `python3 -m unittest tests.test_export_filename_helpers tests.test_exchange_dialogs tests.exchange.test_exchange_custom_fields tests.exchange.test_exchange_json tests.exchange.test_exchange_package tests.app.test_app_shell_startup_core tests.catalog.test_contract_dialogs tests.test_migration_integration`
- Result: `Ran 40 tests in 51.823s` and `OK`

## Future Recommendations

- Split narrower follow-up handoffs only after one of the high-risk waves lands and materially changes the repo shape.
- Refresh this unified strategy when the remaining backlog changes or when Wave 5 introduces new retention/repair policy decisions.
- Keep broad visual restyling and unrelated dock/layout cleanup out of this backlog unless they become required to safely finish one of the defined waves.

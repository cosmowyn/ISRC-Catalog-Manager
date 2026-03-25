# Contract Template Placeholder Phase 0

Current product version: `2.0.0`

Date: 2026-03-24

## Status And Scope

Phase 0 is complete.

This pass stayed in planning, architecture, and continuity scope only.

It did not:

- add schema
- add services
- add UI
- add tests
- alter existing contract, storage, or history behavior

## Phase Goal

Define the full placeholder-template pivot architecture from the live repository state and record a safe implementation path that can survive pauses without drifting back toward the old builder-first direction.

## What Was Implemented In This Pass

- completed a repo-first inspection of the current contracts, storage, history, workspace, and GS1 template surfaces
- reconciled focused planning-worker findings under central oversight
- defined the new product framing as a placeholder-template workspace, not a builder
- defined the proposed domain model, placeholder grammar, ingestion strategy, form-generation strategy, draft lifecycle, PDF/export seam, workspace IA, and admin tooling model
- defined the six implementation phases and the required handoff path for each future phase
- recorded the master plan in `docs/implementation_handoffs/contract-template-placeholder-masterplan.md`

## Source Of Truth Files And Surfaces

Primary code and docs reviewed for Phase 0:

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/contracts/models.py`
- `isrc_manager/contracts/service.py`
- `isrc_manager/contracts/dialogs.py`
- `isrc_manager/file_storage.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/history/cleanup.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/gs1_settings.py`
- `isrc_manager/services/gs1_template.py`
- `isrc_manager/domain/standard_fields.py`
- `docs/catalog-workspace-workflows.md`
- `docs/file_storage_modes.md`
- `docs/implementation_handoffs/backlog-unified-implementation-strategy.md`

Non-authoritative surface explicitly rejected as source of truth:

- `isrc_manager/document_studio/__pycache__`

## Files Changed

- `docs/implementation_handoffs/contract-template-placeholder-masterplan.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-0.md`

## Tests Added Or Updated

None.

## Validation Performed

Phase 0 validation was inspection-based and environment-based only.

Commands run during central oversight included:

- `git status --short`
- `rg --files`
- targeted `rg` / `sed` inspection across contracts, schema, storage, history, workspace, GS1, tests, and docs
- `which textutil`
- `test -d "/Applications/Pages.app" && echo Pages.app-present || echo Pages.app-missing`
- `osascript -e 'tell application "Pages" to get version'`
- `which libreoffice || which soffice || true`
- `textutil -help`

No test suite was executed because this phase landed documentation only.

## What Was Intentionally Deferred

- all schema additions
- placeholder parser implementation
- template library services
- DOCX/Pages ingestion code
- generator UI
- dynamic fill UI
- draft storage implementation
- resolved snapshot and artifact ledger implementation
- PDF export code
- admin cleanup UI

## Risks And Caveats

- the repository has no live source implementation for the earlier document-studio area; only compiled artifacts remain, so that path must not be used as architectural evidence
- DOCX ingestion is practical from the current dependency set, but native Pages parsing is not yet a trustworthy baseline
- exact layout-preserving PDF export will require a renderer adapter seam; Phase 0 only defined the seam and the macOS-first constraints
- one planning worker mis-scoped the pivot into the GS1 template area; only its general repo test-pattern observations were retained, not its GS1-specific phase map

## Worker List And Closures

Central oversight used the following planning workers and closed them after reconciliation:

- `Epicurus` - current repo architecture - closed
- `Gauss` - template ingestion - closed
- `Poincare` - placeholder grammar and mapping - closed
- `Parfit` - dynamic form generation - closed
- `Galileo` - draft persistence and storage - closed
- `Peirce` - PDF and rendering - closed
- `Dewey` - workspace UX and admin - closed
- `Euclid` - tests and phasing strategy - closed
- `Mill` - documentation and continuity - closed

Special QA note:

- `Euclid` returned some useful test-organization references, but central oversight discarded its GS1-specific phase framing because it did not match the requested contract-template pivot

## QA/QC Summary From Central Oversight

Central oversight conclusions:

- the repo already contains the right extension seams for contract-domain reuse, docked workspace integration, storage-mode handling, and history-safe cleanup
- the pivot is safest as a new dedicated workspace and service stack adjacent to the existing contract domain, not as a reinterpretation of `ContractDocuments`
- DOCX should be the first-class template ingestion target
- Pages support requires a macOS adapter seam and must be documented honestly
- draft storage must honor the requested managed-versus-embedded choice without breaking app-owned storage guarantees
- admin tooling must inherit the repo’s existing “record delete versus retained-file cleanup” honesty model

## Exact Safe Pickup Instructions For Phase 1

Start Phase 1 with parser, schema, and service scaffolding only.

Do this next:

1. add a new schema/service slice for:
   - templates
   - template revisions
   - placeholder definitions/bindings
   - drafts
   - resolved snapshots
   - output artifacts
2. implement the canonical placeholder parser and validator
3. define the placeholder registry for known DB namespaces and stable custom-field IDs
4. add tests before UI work:
   - parser unit tests
   - schema-current-target coverage
   - service storage-mode coverage
5. keep new managed directories registered for migration/history support

Do not do this in Phase 1:

- do not repurpose `ContractDocuments` as the template library
- do not build a visual builder
- do not make raw HTML the primary authoring model
- do not depend on `document_studio` compiled remnants
- do not silently resolve ambiguous related records

## Handoff Paths Defined For Future Phases

- `docs/implementation_handoffs/contract-template-placeholder-phase-1.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-2.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-3.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-4.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-5.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-6.md`

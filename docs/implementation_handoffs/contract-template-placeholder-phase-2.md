# Contract Template Placeholder Phase 2

Current product version: `2.0.0`

Date: 2026-03-25

## Status And Scope

Phase 2 is complete.

This pass stayed in template-ingestion and placeholder-scan scope only.

It did:

- add a DOCX-first scan pipeline for imported contract-template revisions
- add a best-effort Pages bridge seam that keeps the original `.pages` source and scans a derived DOCX when available
- persist scan adapter, scan diagnostics, and normalized placeholder inventory on revisions
- add explicit import and re-scan service entrypoints above the Phase 1 storage layer
- add focused scanner, import, re-scan, and schema-migration tests

It did not:

- add UI
- add the symbol generator workspace
- add dynamic fill-form generation
- resolve live DB values into placeholders
- generate previews or PDFs

## Phase Goal

Land the Phase 2 ingestion pipeline for uploaded template sources so the app can accept real Word and Pages documents, scan them for canonical placeholders, persist the scan outcome honestly, and re-scan stored revisions without drifting back toward the old builder-first direction.

## What Was Implemented In This Pass

- added `isrc_manager.contract_templates.ingestion` with:
  - source-format detection for `.docx` and `.pages`
  - direct OOXML scanning for Word body/header/footer XML parts
  - scan diagnostics for bad archives, missing parts, XML parse failures, and blocked Pages bridging
  - a conservative macOS Pages bridge seam using a local conversion adapter
- extended revision models with:
  - `scan_adapter`
  - `scan_diagnostics`
  - scan/import result dataclasses for ingestion workflows
- bumped the database target from `30` to `31`
- extended `ContractTemplateRevisions` to persist:
  - `scan_adapter`
  - `scan_diagnostics_json`
- added explicit `ContractTemplateService` scan/import lifecycle entrypoints:
  - `scan_source_bytes(...)`
  - `scan_source_path(...)`
  - `import_revision_from_bytes(...)`
  - `import_revision_from_path(...)`
  - `rescan_revision(...)`
  - `set_active_revision(...)`
- kept `add_revision_from_*` as low-level storage helpers and prevented blocked imports from auto-promoting themselves to the active revision
- made Pages rescans deterministic from stored revision bytes rather than the original filesystem path
- preserved existing placeholder bindings across successful re-scans by canonical symbol
- preserved the last successful placeholder inventory when a later re-scan is blocked by environment/tooling constraints
- exported the new ingestion and scan surfaces through `isrc_manager/services/__init__.py`

## Source Of Truth Files And Surfaces

Primary implementation files for Phase 2:

- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/ingestion.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/services/__init__.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/constants.py`

Primary test surfaces for Phase 2:

- `tests/contract_templates/_support.py`
- `tests/contract_templates/test_scanner.py`
- `tests/contract_templates/test_revision_service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_30_31.py`

## Files Changed

- `docs/implementation_handoffs/contract-template-placeholder-phase-2.md`
- `isrc_manager/constants.py`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/ingestion.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/services/__init__.py`
- `isrc_manager/services/schema.py`
- `tests/contract_templates/__init__.py`
- `tests/contract_templates/_support.py`
- `tests/contract_templates/test_scanner.py`
- `tests/contract_templates/test_revision_service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_30_31.py`

## Tests Added Or Updated

Added:

- `tests/contract_templates/__init__.py`
- `tests/contract_templates/_support.py`
- `tests/contract_templates/test_scanner.py`
- `tests/contract_templates/test_revision_service.py`
- `tests/database/test_schema_migrations_30_31.py`

Updated:

- `tests/database/_schema_support.py`

## Validation Performed

Commands run during Phase 2 verification:

- `python3 -m py_compile isrc_manager/contract_templates/service.py isrc_manager/contract_templates/ingestion.py isrc_manager/services/__init__.py tests/contract_templates/_support.py tests/contract_templates/test_scanner.py tests/contract_templates/test_revision_service.py tests/database/_schema_support.py tests/database/test_schema_migrations_30_31.py`
- `python3 -m unittest tests.contract_templates.test_scanner`
- `python3 -m unittest tests.contract_templates.test_revision_service`
- `python3 -m unittest tests.test_contract_template_parser tests.test_contract_template_service tests.database.test_schema_current_target tests.database.test_schema_migrations_29_30 tests.database.test_schema_migrations_30_31`

All passed.

## What Was Intentionally Deferred

- symbol generator UI and placeholder catalog browsing
- known-field mapping dictionary UX
- smart manual-field type inference beyond raw placeholder scanning
- dynamic fill-form generation
- draft editing/resume UX
- resolved preview generation
- PDF export
- admin/archive UI for templates and drafts

## Risks And Caveats

- the Pages bridge remains intentionally conservative and best-effort; Phase 2 persists honest blocked diagnostics instead of pretending all `.pages` imports are universally supported
- DOCX scanning currently targets body, header, and footer XML parts only; richer Word structures can be layered in later without changing the import contract
- blocked re-scans preserve the last successful placeholder inventory on purpose so host-specific bridge failures do not destroy previously usable metadata
- Phase 2 still does not infer widget types or DB resolver semantics automatically; it only stores the canonical placeholder inventory and any explicitly provided bindings

## Worker List And Closures

Central oversight used the following planning and implementation workers and closed them after reconciliation:

- `Sagan` - DOCX/XML precedent inspection - closed
- `Wegener` - Pages bridge/environment inspection - closed
- `Anscombe` - contract-template Phase 2 service-shape inspection - closed

## QA/QC Summary From Central Oversight

Central oversight conclusions:

- the pivot remains external-template-first and placeholder-driven; no builder UI, HTML authoring path, or `ContractDocuments` repurposing leaked back into the implementation
- Phase 2 now has a clean import coordinator above the Phase 1 storage layer, which keeps storage primitives reusable while making ingestion behavior explicit
- scan truth is persisted honestly on revisions through status, adapter, diagnostics, and placeholder inventory metadata
- blocked Pages imports no longer masquerade as healthy revisions and do not replace an already active, ready revision
- regression coverage still protects the Phase 1 parser and storage scaffold while new tests verify DOCX extraction, Pages bridging, and re-scan behavior

## Exact Safe Pickup Instructions For Phase 3

Start Phase 3 with the symbol-generator workspace and mapping dictionary.

Do this next:

1. add a symbol-generator surface that enumerates valid canonical placeholders from real database-backed entities and fields
2. define a reusable placeholder catalog/dictionary layer that can drive copy/paste insertion guidance and later form-widget defaults
3. expose known DB-bound placeholders distinctly from manual placeholders
4. keep the generator aligned with the Phase 1 canonical grammar and the Phase 2 scan/import inventory
5. add tests for:
   - stable canonical symbol generation
   - field-to-symbol catalog grouping
   - duplicate/invalid catalog entry rejection

Do not do this in Phase 3:

- do not build the dynamic fill form yet
- do not guess resolver targets from free-form placeholder names
- do not widen template-source support beyond `.docx` and `.pages`
- do not introduce PDF/export logic early

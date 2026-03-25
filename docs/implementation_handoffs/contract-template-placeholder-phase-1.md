# Contract Template Placeholder Phase 1

Current product version: `2.0.0`

Date: 2026-03-25

## Status And Scope

Phase 1 is complete.

This pass stayed in backend scaffold scope only.

It did:

- add the canonical placeholder parser
- add the new contract-template package and service layer
- add schema version `30` with contract-template storage tables
- register new managed roots for storage/history coverage
- add parser, service, schema, and history/path tests

It did not:

- add UI
- ingest DOCX or Pages content
- scan uploaded files
- resolve live DB values into placeholders
- generate PDFs

## Phase Goal

Land the strict placeholder grammar, core domain model, schema/storage scaffold, and draft/template service surfaces needed for the placeholder-template pivot without reintroducing the old builder-first direction.

## What Was Implemented In This Pass

- added `isrc_manager.contract_templates` with:
  - payload/record dataclasses
  - strict placeholder parsing and extraction helpers
  - `ContractTemplateService`
- locked Phase 1 placeholder syntax to:
  - `{{db.namespace.key}}`
  - `{{manual.key}}`
- enforced parser normalization, malformed-token rejection, custom-field `cf_<id>` validation, extraction, and deduplication
- bumped the database target from `29` to `30`
- added schema/storage tables for:
  - `ContractTemplates`
  - `ContractTemplateRevisions`
  - `ContractTemplatePlaceholders`
  - `ContractTemplatePlaceholderBindings`
  - `ContractTemplateDrafts`
  - `ContractTemplateResolvedSnapshots`
  - `ContractTemplateOutputArtifacts`
- added dual-storage guard triggers for revisions and drafts
- extended dual-storage backfill wiring for new revision/draft tables
- registered managed roots:
  - `contract_template_sources`
  - `contract_template_drafts`
- exported the new service/parser/dataclass surface through `isrc_manager/services/__init__.py`
- added Phase 1 continuity coverage in tests

## Source Of Truth Files And Surfaces

Primary implementation files for Phase 1:

- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/contract_templates/parser.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/__init__.py`
- `isrc_manager/constants.py`
- `isrc_manager/paths.py`
- `isrc_manager/history/manager.py`
- `pyproject.toml`

Primary test surfaces for Phase 1:

- `tests/test_contract_template_parser.py`
- `tests/test_contract_template_service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_29_30.py`
- `tests/test_paths.py`
- `tests/history/_support.py`
- `tests/history/test_history_snapshots.py`

## Files Changed

- `docs/implementation_handoffs/contract-template-placeholder-phase-1.md`
- `isrc_manager/contract_templates/__init__.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/contract_templates/parser.py`
- `isrc_manager/contract_templates/service.py`
- `isrc_manager/constants.py`
- `isrc_manager/paths.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/services/__init__.py`
- `isrc_manager/services/schema.py`
- `pyproject.toml`
- `tests/test_contract_template_parser.py`
- `tests/test_contract_template_service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_29_30.py`
- `tests/test_paths.py`
- `tests/history/_support.py`
- `tests/history/test_history_snapshots.py`

## Tests Added Or Updated

Added:

- `tests/test_contract_template_parser.py`
- `tests/test_contract_template_service.py`
- `tests/database/test_schema_migrations_29_30.py`

Updated:

- `tests/database/_schema_support.py`
- `tests/test_paths.py`
- `tests/history/_support.py`
- `tests/history/test_history_snapshots.py`

## Validation Performed

Commands run during Phase 1 verification:

- `python3 -m unittest tests.test_contract_template_parser`
- `python3 -m unittest tests.test_contract_template_service`
- `python3 -m unittest tests.database.test_schema_current_target tests.database.test_schema_migrations_29_30`
- `python3 -m unittest tests.test_paths tests.history.test_history_snapshots`

All passed.

## What Was Intentionally Deferred

- DOCX placeholder scanning
- Pages conversion/adapter handling
- template import UI
- symbol generator UI
- dynamic form generation
- DB-backed picker widgets
- smart manual field inference at the UI layer
- draft browsing/admin UI
- resolved document preview generation
- PDF export

## Risks And Caveats

- Phase 1 stores template sources and draft payloads safely, but it does not yet inspect uploaded document contents
- the new service assumes the profile DB has already been initialized/migrated by `DatabaseSchemaService`
- managed-file revision/draft storage requires a configured `data_root`
- the placeholder parser is intentionally strict and will reject non-canonical shorthand forms that may appear in legacy experimental templates

## Worker List And Closures

Central oversight used the following implementation workers and closed them after reconciliation:

- `Herschel` - schema/migration inspection - closed
- `Erdos` - service/storage pattern inspection - closed
- `Ptolemy` - paths/history/package-export inspection - closed
- `Pauli` - contract-template package implementation support - closed
- `Hypatia` - managed-root/history test slice - closed

## QA/QC Summary From Central Oversight

Central oversight conclusions:

- the new backend scaffold is isolated from `ContractDocuments` and does not leak the earlier builder-first direction back into the codebase
- Phase 1 now has a stable, testable storage/model/service foundation for template sources, placeholders, drafts, resolved snapshots, and artifact metadata
- dual-storage semantics are explicit and schema-guarded for the two mutable storage-bearing tables introduced in this phase
- new managed roots are now visible to both storage layout and history snapshot/restore machinery
- the implementation remains honest about scope: no fake ingestion, no guessed values, no PDF/export shortcuts

## Exact Safe Pickup Instructions For Phase 2

Start Phase 2 with template ingestion and placeholder scan plumbing.

Do this next:

1. add source-format-aware ingestion services for imported template files
2. make DOCX the first-class scan target using repo-local ZIP/XML parsing
3. add a Pages adapter seam that stores the original `.pages` file but scans a derived format when available
4. persist scan diagnostics and normalized placeholder inventory through the Phase 1 service/schema surfaces
5. add tests for:
   - DOCX placeholder extraction from body text, tables, and headers/footers
   - ingestion error reporting
   - revision re-scan behavior

Do not do this in Phase 2:

- do not add builder UI
- do not guess placeholder meaning from filenames or surrounding text
- do not treat PDF as a template source format
- do not bypass the canonical parser
- do not silently collapse malformed placeholders into valid ones

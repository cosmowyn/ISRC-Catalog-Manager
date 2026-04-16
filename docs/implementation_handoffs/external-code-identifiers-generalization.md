# External Code Identifiers Generalization

## Status

This handoff documents the completed Codespace external-identifier generalization pass that lands schema target `40`.

It extends the earlier registry workspace implementation from catalog-only external storage to a shared, typed external identifier model for this closed built-in set:

- `catalog_number`
- `contract_number`
- `license_number`
- `registry_sha256_key`

This handoff is additive to, and partially supersedes, the earlier catalog-only external-storage wording in:

- [`docs/implementation_handoffs/central-code-registry-workspace-and-integration.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/central-code-registry-workspace-and-integration.md)
- [`docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-cleanup-and-data-layout-handoff.md)
- [`docs/implementation_handoffs/storage-migration-reliability-fix.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/storage-migration-reliability-fix.md)

Where this handoff conflicts with the old `External Catalog` wording, this handoff is now the source of truth.

## What Changed

The old external catalog concept was generalized into `ExternalCodeIdentifiers`, a typed external-value store owned by Codespace.

Implemented layers:

- [`isrc_manager/code_registry/models.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/code_registry/models.py)
- [`isrc_manager/code_registry/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/code_registry/service.py)
- [`isrc_manager/code_registry/widgets.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/code_registry/widgets.py)
- [`isrc_manager/code_registry/workspace.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/code_registry/workspace.py)
- [`isrc_manager/services/schema.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/services/schema.py)
- [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py)
- [`isrc_manager/releases/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/releases/service.py)
- [`isrc_manager/contracts/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/contracts/service.py)
- [`isrc_manager/exchange/models.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/exchange/models.py)
- [`isrc_manager/exchange/service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/exchange/service.py)
- [`isrc_manager/exchange/dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/isrc_manager/exchange/dialogs.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)

UI naming is now deliberately split:

- storage/model term: `ExternalCodeIdentifiers`
- workspace/UI term: `External Identifiers`

They refer to the same domain concept.

## Final Architecture

### 1. External identifier table

Authoritative external storage now lives in `ExternalCodeIdentifiers` with these business columns:

- `category_system_key`
- `value`
- `normalized_value`
- `origin_record_kind`
- `origin_record_id`
- `provenance_kind`
- `classification_status`
- `classification_reason`
- `source_label`
- `matched_registry_entry_id`

`origin_record_kind` and `origin_record_id` are provenance only. They mean "first captured from / first backfilled from." They are nullable, write-once metadata and are not consulted for live linkage authority.

Rows are reusable. One external identifier row can be linked from multiple business records.

Assignment semantics are centralized in `CodeRegistryService`:

1. normalize by category
2. look up `(category_system_key, normalized_value)`
3. attach the existing row if present
4. otherwise create one new row and attach it

No per-owner duplication is allowed for the same typed normalized external value.

### 2. Closed category set

External identifier workflows are hard-gated to this closed set in this patch:

- `catalog_number`
- `contract_number`
- `license_number`
- `registry_sha256_key`

Other internal categories may still exist elsewhere in the registry, but they are not enabled for the external identifier workflow in this patch.

### 3. Authority contract

For each supported field, runtime authority is now fixed and centralized:

1. internal registry FK, if present
2. else external code identifier FK, if present
3. else legacy text mirror for display compatibility only
4. legacy text never overrides a Codespace link

Mutual exclusivity is enforced in two places:

- service validation rejects dual-authority payloads explicitly
- schema target `40` adds SQLite `CHECK` constraints so a supported field can hold internal, external, or neither, but never both

Implemented field pairs:

- `Tracks.catalog_registry_entry_id` vs `Tracks.catalog_external_code_identifier_id`
- `Releases.catalog_registry_entry_id` vs `Releases.catalog_external_code_identifier_id`
- `Contracts.contract_registry_entry_id` vs `Contracts.contract_external_code_identifier_id`
- `Contracts.license_registry_entry_id` vs `Contracts.license_external_code_identifier_id`
- `Contracts.registry_sha256_key_entry_id` vs `Contracts.registry_sha256_key_external_code_identifier_id`

### 4. Normalization and classification

Normalization is category-specific and lives in `CodeRegistryService`. UI, import, migration, and persistence all call the same service rules.

External normalization rules:

- `catalog_number`, `contract_number`, `license_number`: trimmed, whitespace-folded, case-insensitive matching, raw punctuation preserved in `value`
- `registry_sha256_key`: trimmed only for dedupe, no hash-format validation, case and punctuation preserved externally

Internal rules remain strict and built-in-specific:

- sequential built-ins still require canonical `<PREFIX><YY><NNNN>`
- internal `registry_sha256_key` still requires lowercase 64-hex

External key rule:

- any non-empty external key is admissible
- a valid-looking 64-hex string still remains external unless there is explicit internal context or a concrete internal match selected by the service

Persisted external statuses are now a closed set:

- `external`
- `mismatch`
- `shadowed_by_internal`
- `migration_conflict`

Import ambiguity is staged only in import-session state. It is not persisted as an external row status.

## UI And Workflow Changes

### Codespace workspace

The old `External Catalogs` tab is now `External Identifiers`.

The workspace now filters and displays typed external rows for all four supported built-ins, including:

- type
- usage count
- classification/provenance
- promote/reclassify actions

### Track and release editors

Track and release catalog workflows now run through the generic `CodeIdentifierSelector`.

Unspecified mode behavior was tightened:

- explicit internal mode still forces internal capture/linkage
- explicit external mode still forces external storage
- plain text with no explicit mode now resolves centrally
- canonical internal catalog values are captured internally instead of being forced external by default

### Contract editor

Contract Number, License Number, and Registry SHA-256 Key now use the same selector pattern.

Save-time service rules enforce:

- internal and external authority are mutually exclusive
- stale dirty-state dual links are rejected even if the UI fails to clear them
- external mode never generates values
- internal mode only generates through the matching built-in category

Reclassification from external to internal is non-destructive:

- owner links move to the internal FK
- the external row remains
- provenance survives
- `matched_registry_entry_id` is recorded

## Import And Review Changes

The exchange layer is no longer catalog-only internally.

Implemented changes:

- generic `ExchangeIdentifierClassificationOutcome`
- typed `identifier_totals` in `ExchangeImportReport`
- staged `Identifier Review` tab in the import dialog
- `identifier_overrides` in `ExchangeImportOptions`

Import review timing is explicit:

- review choices stay in memory only
- no temporary DB rows are created before apply
- persistence happens only on final apply

Current import behavior split:

- owner-bound catalog fields still attach to track/release authority through the shared registry service
- imported unbound `contract_number`, `license_number`, and `registry_sha256_key` values can be staged, reviewed, type-overridden, and stored directly into `ExternalCodeIdentifiers`

The review key is deterministic per staged value:

- row index
- source header
- mapped target field
- raw value

That keeps the override path deterministic and testable.

## Migration Summary

### 39 -> 40

Migration `39 -> 40` is the major storage cutover.

It performs:

- create `ExternalCodeIdentifiers`
- add new external FK columns on owner tables
- rebuild `Tracks`, `Releases`, and `Contracts` with mutual-exclusion checks
- copy legacy `ExternalCatalogIdentifiers` rows into `ExternalCodeIdentifiers`
- backfill track/release external links to `catalog_external_code_identifier_id`
- backfill contract/license/key authority using centralized classification
- write deterministic machine-readable diagnostics into `_MigrationDiagnostics`

Precedence order during backfill:

1. existing internal FK wins
2. else existing external FK wins
3. else classify legacy text

Conflict handling:

- conflicting leftover text is preserved as compatibility text only
- it never overrides the authoritative link
- migration diagnostics count conflicts per category and conflict type

### Earlier migration-chain safety fixes

This patch also had to harden older migrations because current-schema tables now reference the generalized identifier storage:

- `18 -> 19` now ensures code-registry tables exist before release-table creation/migration
- code-registry immutability trigger creation is now table-aware, so older schemas do not fail while referenced tables are still absent
- `39 -> 40` now drops/recreates `vw_Licenses` and refreshes the immutability trigger around table rebuilds

These were required to keep the full migration chain valid instead of only making new databases pass.

## Retired Runtime Authority

Retired as live authority in this patch:

- `ExternalCatalogIdentifiers`
- `external_catalog_identifier_id` as a storage authority column on live `Tracks` and `Releases`
- catalog-only exchange outcome/report semantics
- catalog-only workspace naming as the user-facing concept
- any direct attempt to treat legacy mirror text as authoritative when an internal or external FK exists

Important nuance:

- some Python compatibility aliases still exist in payloads/models/widgets to avoid a hard break across neighboring UI code and tests
- those aliases are not authoritative storage
- live runtime storage authority is the new FK pair contract described above

## QC And QA Performed

### QC

Verified:

- authority inference is centralized in `CodeRegistryService`
- dual-link payloads are rejected at service level
- category-specific normalization is centralized
- migration diagnostics are machine-readable
- the import review flow stays staged until apply
- external SHA-256 values are accepted externally without format policing
- release/track canonical catalog values still auto-capture internally when no explicit mode is supplied

### QA

Validated workflows:

- track create with canonical catalog text captures internal authority
- release create/update can switch between external and internal catalog authority
- contract editor still initializes and exposes the expected registry controls
- exchange dialog supports staged external identifier review overrides
- unbound imported identifier values store into Codespace external storage under the selected type
- release migration chain still succeeds from older schema versions

## Tests Added Or Updated

Added:

- [`tests/database/test_schema_migrations_39_40.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/database/test_schema_migrations_39_40.py)

Updated:

- [`tests/exchange/test_registry_classification.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/exchange/test_registry_classification.py)
- [`tests/test_exchange_dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_exchange_dialogs.py)
- [`tests/test_code_registry_service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_code_registry_service.py)
- [`tests/test_code_registry_workflow_integration.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_code_registry_workflow_integration.py)
- [`tests/test_code_registry_workspace.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_code_registry_workspace.py)
- [`tests/test_repertoire_dialogs.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_repertoire_dialogs.py)
- [`tests/test_release_service.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/test_release_service.py)
- [`tests/ci_groups.py`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/tests/ci_groups.py)

## Validation Runs

Headless validation completed with:

- `./.venv/bin/python -m py_compile isrc_manager/code_registry/service.py isrc_manager/code_registry/widgets.py isrc_manager/services/tracks.py isrc_manager/releases/service.py isrc_manager/contracts/service.py isrc_manager/services/schema.py isrc_manager/exchange/models.py isrc_manager/exchange/service.py isrc_manager/exchange/dialogs.py ISRC_manager.py tests/exchange/test_registry_classification.py tests/test_exchange_dialogs.py tests/database/test_schema_migrations_39_40.py tests/ci_groups.py`
- `QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m unittest tests.test_exchange_dialogs tests.exchange.test_registry_classification tests.test_code_registry_service tests.test_code_registry_workflow_integration tests.test_code_registry_workspace tests.database.test_schema_migrations_39_40 tests.test_repertoire_dialogs tests.test_release_service -v`

That combined run finished green with `85` tests.

## Known Edge Cases And Follow-Up Risks

- The live runtime now prefers new authority links, but several compatibility attribute names still mention `external_catalog_identifier_id`. Those aliases should be removed in a future cleanup once neighboring code no longer depends on them.
- Schema helpers still keep the legacy `ExternalCatalogIdentifiers` table around for migration history and compatibility. That table should be considered inert after migration target `40`, not a supported runtime authority.
- The import review tab currently targets the unbound external identifier fields. If future import sources need richer metadata-driven ambiguity handling beyond those mapped fields, extend the staged review model rather than adding ad hoc UI logic.
- `ISRC_manager.py` remains manually formatted by repo convention, so changes there were validated by compile and targeted tests rather than a formatter pass.

## Resume Guidance

If another engineer continues this area, read in this order:

1. this handoff
2. `central-code-registry-workspace-and-integration.md`
3. the schema target `40` migration in `isrc_manager/services/schema.py`
4. the generic identifier rules in `isrc_manager/code_registry/service.py`

If you touch authority or normalization rules, rerun at minimum:

- `tests.test_code_registry_service`
- `tests.test_code_registry_workflow_integration`
- `tests.exchange.test_registry_classification`
- `tests.database.test_schema_migrations_39_40`

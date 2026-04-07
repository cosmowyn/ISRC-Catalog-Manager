# Central Code Registry Workspace and Integration

## 1. Code fields audited
- Centralized live in-scope catalog fields: `Tracks.catalog_number` and `Releases.catalog_number`.
- Added new contract-side registry-backed fields on `Contracts`: `contract_number`, `license_number`, and `registry_sha256_key`.
- Preserved out-of-scope identifiers outside the registry: ISRC, ISWC, work registration numbers, BUMA work numbers, GS1 contract numbers, and watermark/authenticity keys.
- Confirmed that legacy `Licenses` flows remain document/archive storage, not the new business-code authority.

## 2. Standard categories wired
- Built-in registry categories are seeded automatically:
  - `catalog_number`
  - `contract_number`
  - `license_number`
  - `registry_sha256_key`
- Custom categories are supported through the new workspace.
- Sequential categories use user-configurable prefixes.

## 3. Registry model chosen
- Internal authoritative model:
  - `CodeRegistryCategories`
  - `CodeRegistrySequences`
  - `CodeRegistryEntries`
- Flexible foreign catalog model:
  - `ExternalCatalogIdentifiers`
- Owner links added to:
  - `Tracks.catalog_registry_entry_id`
  - `Tracks.external_catalog_identifier_id`
  - `Releases.catalog_registry_entry_id`
  - `Releases.external_catalog_identifier_id`
  - `Contracts.contract_registry_entry_id`
  - `Contracts.license_registry_entry_id`
  - `Contracts.registry_sha256_key_entry_id`
- Text shim fields remain in place on tracks, releases, and contracts so existing readers, exports, and template resolution continue to work.

## 4. Generation and immutability rules
- Sequential internal codes use `<PREFIX><YY><NNNN>`.
- Sequence state is tracked per category and year in `CodeRegistrySequences`.
- Canonical imported/manual internal values advance the high-water mark without filling gaps.
- Internal entries are immutable after insert.
- DB uniqueness is enforced on normalized internal values and on `(category_id, sequence_year, sequence_number)` for sequential rows.
- DB triggers prevent in-place update/delete of internal registry entries.
- Undo/redo works by relinking owners, not by mutating immutable registry rows.

## 5. Watermark-key distinction handling
- The new key is named `Registry SHA-256 Key` everywhere.
- It lives in the registry category `registry_sha256_key`.
- It is generated with secure randomness through `hashlib.sha256(secrets.token_bytes(32)).hexdigest()`.
- No existing authenticity or watermark tables, dialogs, exports, or tests were repurposed.
- Contract editor, contract-template fill form, workspace labels, and tests all keep this key distinct from watermark/authenticity flows.

## 6. External / foreign catalog identifier handling
- Foreign or non-canonical catalog values live in `ExternalCatalogIdentifiers`, not in the immutable internal registry.
- Track/release catalog workflows now support two clear modes:
  - `Internal Registry`
  - `External Catalog`
- Reused external identifiers are now shared by normalized value, so one catalog value is stored once and surfaced with a usage count instead of being duplicated once per owner.
- Canonical-looking values with no configured prefix stay safe as external candidates until the user configures prefixes and reclassifies them.
- Known-prefix malformed values are preserved as external with mismatch metadata instead of being rejected.

## 7. Migration behavior
- Schema target is now `38`.
- Migration `35 -> 36` creates the new registry tables, owner-link columns, contract registry fields, indexes, and immutability triggers.
- Migration `36 -> 37` deduplicates external catalog rows by normalized value and rewires owner links onto shared external identifier rows.
- Migration `37 -> 38` relaxes the delete trigger so unused `Registry SHA-256 Key` rows can be deleted while other internal immutable rows remain protected.
- Existing track/release catalog strings are backfilled through the same classifier used elsewhere:
  - with no configured catalog prefix they remain preserved as external rows
  - canonical values can later be promoted/reclassified after prefix setup
- Existing catalog text is preserved exactly in shim columns.
- No destructive backfill was done for contract/license/hash values because those fields did not exist previously.

## 8. Editor-workflow integration
- Added a shared `CatalogIdentifierSelector` for track/release catalog workflows.
- Wired registry-backed catalog handling into:
  - Add Track
  - Add Album
  - track edit flows
  - Release Editor
- Bulk edit remains selection/manual-oriented and intentionally does not mass-generate new IDs.
- Added a `Registry IDs` section to `ContractEditorDialog` with searchable selectors and generate actions for:
  - Contract Number
  - License Number
  - Registry SHA-256 Key
- Contract create/update/delete now run through snapshot-history wrappers in `ISRC_manager.py`.
- Generated rows are persisted immediately as issued immutable identities; if an editor is canceled afterward, the row remains unlinked and is visible in the registry workspace.
- The internal registry workspace can now link an already-issued unassigned value later with `Link Selected Value`.
- Unused `Registry SHA-256 Key` rows can be deleted from the workspace without weakening the immutability guarantees for other internal code rows.

## 9. Symbol-workflow integration
- Contract-template symbol catalog now exposes:
  - `{{db.contract.contract_number}}`
  - `{{db.contract.license_number}}`
  - `{{db.contract.registry_sha256_key}}`
- Existing track/release catalog placeholders remain entity-backed and now resolve through registry-backed owner fields.
- Fill-form selector groups now expose in-place generate actions for registry-backed symbols:
  - `Generate Catalog Number` for track/release selectors
  - `Generate Contract Number`
  - `Generate License Number`
  - `Generate Registry SHA-256 Key`
- Generated values are assigned directly to the selected entity before template filling continues.

## 10. Tests added and updated
- Added:
  - `tests/test_code_registry_service.py`
  - `tests/test_code_registry_workspace.py`
  - `tests/test_code_registry_workflow_integration.py`
  - `tests/exchange/test_registry_classification.py`
  - `tests/contract_templates/test_registry_generation.py`
  - `tests/database/test_schema_migrations_35_36.py`
- Updated:
  - `tests/database/_schema_support.py`
  - `tests/catalog/_contract_rights_asset_support.py`
  - `tests/catalog/test_contract_dialogs.py`
  - `tests/contract_templates/test_catalog.py`
  - `tests/test_background_app_services.py`
  - `tests/test_repertoire_dialogs.py`
- Verified headless, no-popup-friendly test behavior with patched message-box paths and the existing Qt test harness.

## 11. Risks and caveats
- Built-in prefixes are intentionally user-configured, so legacy canonical-looking catalog values remain external until the prefix is set and reclassification is run.
- Generated immutable rows can remain unlinked if the user cancels after generation; this is intentional and discoverable in the workspace.
- Shared external identifiers now depend on normalized-value deduplication, so any future change to external normalization rules needs migration care.
- `ISRC_manager.py` was updated manually and was not included in the automatic Black/Ruff pass because the repository treats it as a manual-format exception.
- Full repository-wide unittest discovery and mypy were not run in this pass; targeted compile, Ruff, Black, and the affected unittest modules were run instead.

## 12. Explicit centralization statement
- App-managed internal catalog numbers, contract numbers, license numbers, and the new `Registry SHA-256 Key` are now centralized in one authoritative registry.
- Foreign and third-party catalog identifiers remain safely supported in a separate external model without weakening internal uniqueness, sequencing, or immutability rules.

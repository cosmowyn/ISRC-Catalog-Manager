# Registry Code Generation And Assignment Fix

## 1. Flawed current behavior found

- Contract Number and License Number generation was not wired as an authoritative workflow. The system mostly depended on editor-side hint text, ad hoc selector actions, or save-time capture.
- Contract template export resolved registry-backed placeholders as plain database fields, so final export did not reliably generate and assign missing Contract Number, License Number, Registry SHA-256 Key, or Catalog Number values.
- `generate_registry_value_for_contract()` always issued a fresh value, even when the contract already had a linked value that should have been reused.
- Workspace generation favored catalog and hash workflows and did not intentionally support contract/license generation, unlinked deletion for sequential entries, or explicit admin realignment.
- Sequential issuance used `CodeRegistrySequences.last_sequence_number`, which prevented the intended “reuse only the deleted highest slot” behavior.

## 2. Corrected template-time generation model

- Contract template symbol catalog entries now declare whether a placeholder is backed by a registry category and owner kind.
- Registry-backed template symbols are now draft-owned during contract-template fill/export workflows. They are no longer modeled as requiring a preselected `Contracts`, `Tracks`, or `Releases` record.
- The first saved draft becomes the authoritative lifecycle owner for template-issued registry values.
- Final export paths now resolve registry-backed placeholders through authoritative draft-registry assignments instead of reading blank record fields directly.
- Export-time generation now supports:
  - `{{db.track.catalog_number}}`
  - `{{db.release.catalog_number}}`
  - `{{db.contract.contract_number}}`
  - `{{db.contract.license_number}}`
  - `{{db.contract.registry_sha256_key}}`
- On first draft save, missing draft-backed registry values are generated, linked to that draft, and then reused across later saves, previews, exports, and revision changes for the same draft lifecycle.
- Final export reuses existing draft assignments instead of issuing duplicates.
- Preview and HTML session materialization remain non-destructive before the first saved draft exists. Once a draft exists, preview resolves through its persisted draft-owned assignments.

## 3. Corrected manual generation model

- Manual generation now coexists cleanly with template-time generation instead of competing with it.
- Contract editor registry fields now proactively enable or disable generation based on registry configuration and still support explicit manual issuance.
- Contract template fill-form registry placeholders are now automatic draft fields instead of selector-driven generation targets.
- Code Registry workspace generation now supports category-driven issuance for contract, license, catalog, and SHA-256 categories.
- Workspace generation can be followed by explicit assignment for unlinked entries, and contract-bound entries can be explicitly realigned by admins.

## 4. Prefix/namespace gating and nudge strategy

- Sequential generation now routes through `generation_unavailable_reason(...)`.
- Generation is disabled when:
  - the category is inactive
  - the category is missing
  - the category is not sequential/SHA-256 generatable
  - the sequential category has no valid configured prefix/namespace
- Contract editor, catalog selector, template fill-form buttons, workspace generation button, and export-time issuance all use the same gating rules.
- User nudges now point people to `Code Registry > Categories` to configure the missing prefix/namespace before generation can continue.
- Export raises a clear `ContractTemplateExportError` instead of silently failing or issuing malformed values.

## 5. Unlinked deletion strategy

- Internal registry entries remain immutable in value, but unlinked entries can now be deleted safely regardless of category.
- Service-layer deletion checks usage first and rejects deletion when any track, release, or contract still links the entry.
- Draft-owned contract-template registry assignments are now included in usage checks and deletion protection.
- Schema trigger protection was updated to match the new service rule so linked entries stay protected even if deletion is attempted below the UI layer.
- This now covers unlinked sequential entries in addition to unlinked Registry SHA-256 keys.

## 6. Admin reassignment strategy

- Contract Number, License Number, and Registry SHA-256 Key entries now support explicit admin realignment.
- Realignment is handled by a dedicated service method instead of accidental overwrite behavior.
- Realignment clears the prior contract link, assigns the entry to the new contract, and blocks the move if the destination already owns a different linked value.
- Normal assignment still refuses to silently overwrite an existing contract-bound registry value.

## 7. Next-code generation rule implemented

- Sequential issuance now derives the next number from the highest currently existing sequence in the category/year series.
- Internal lower gaps are not reused.
- If the deleted value was the current highest slot, that highest slot becomes reusable on the next issuance.
- `CodeRegistrySequences.last_sequence_number` no longer forces the series forward after the highest surviving entry was removed.

## 8. Tests added and updated

- Updated `tests/test_code_registry_service.py` for:
  - prefix gating
  - non-highest deletion gap behavior
  - highest-slot reuse
  - unlinked sequential deletion
  - linked deletion protection
  - contract realignment
  - conflict-blocked realignment
  - ensure/reuse/capture contract flows
- Updated `tests/test_code_registry_workspace.py` for:
  - contract-number generation from the workspace
  - generation disable/nudge behavior when prefixes are missing
  - generic unlinked deletion messaging
  - explicit contract realignment
- Updated `tests/contract_templates/test_registry_generation.py` for:
  - License Number manual generation in the fill workflow
  - fill-form generation disable/nudge behavior when prefixes are missing
- Updated `tests/catalog/_contract_rights_asset_support.py` and `tests/catalog/test_contract_dialogs.py` for contract editor gating behavior.
- Expanded `tests/contract_templates/test_export_service.py` for:
  - export-time draft-owned generation and assignment
  - reuse of existing draft-linked entries
  - non-destructive preview behavior
  - prefix-gated export failure
  - draft-linked deletion protection
- Updated `tests/contract_templates/test_form_generation.py` so registry-backed template symbols are auto-resolved draft fields instead of selector fields.

## 9. Risks and caveats

- First draft save is now the authoritative issuance point for template-owned registry placeholders. If draft save succeeds and a later render step fails, the draft-linked codes remain issued. This is intentional.
- Preview remains non-destructive before the first saved draft exists, so unsaved drafts may still show unresolved registry placeholders until the first draft has been persisted.
- Realignment is intentionally limited to contract-bound one-to-one categories to avoid ambiguous ownership semantics.

## 10. Outcome statement

Contract Number and License Number generation now works in both places it needs to work:

- during draft creation / draft save / final export when a registry-backed symbol requires an authoritative value for that specific drafted document
- during manual editor/workspace workflows when a user explicitly generates values by hand

Sequence generation now follows the intended rule:

- lower deleted gaps are not reused
- deleting the highest value makes that highest slot reusable
- prefix-aware gating blocks invalid issuance until configuration is fixed

## 11. Prompt data hygiene confirmation

- Prompt example codes were not copied into source, tests, fixtures, docs, comments, logs, or handoff text.
- New coverage uses sanitized repo-safe values and generic prefixes already consistent with the repository test style.

## Verification

- `python3 -m unittest tests.test_code_registry_service tests.test_code_registry_workspace tests.contract_templates.test_export_service tests.contract_templates.test_registry_generation tests.catalog.test_contract_dialogs`
- `python3 -m unittest tests.test_code_registry_workflow_integration tests.contract_templates.test_catalog tests.contract_templates.test_dialogs tests.contract_templates.test_form_generation tests.test_repertoire_dialogs`
- `python3 -m py_compile isrc_manager/contract_templates/dialogs.py tests/test_code_registry_workspace.py tests/contract_templates/test_export_service.py`

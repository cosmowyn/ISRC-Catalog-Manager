# Party Manager Expansion and Template Binding Handoff

Current product version: local working tree on `phase1-contract-template-scaffold`  
Date: 2026-03-25

## Status

Implemented.

This pass expands the canonical party authority chain, makes the Party Manager editor safe for the full expanded party payload, adds multi-alias support through a normalized child table, and exposes the relevant `db.party.*` fields to the contract/license template workflow.

## Current Party Model Audited

The canonical party authority remains the `Parties` table and `PartyService`, reused by:

- `WorkContributors.party_id`
- `ContractParties.party_id`
- `RightsRecords.granted_by_party_id`
- `RightsRecords.granted_to_party_id`
- `RightsRecords.retained_by_party_id`

Source-of-truth runtime surfaces:

- `isrc_manager/services/schema.py`
- `isrc_manager/parties/models.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/parties/dialogs.py`
- `isrc_manager/contract_templates/catalog.py`
- `isrc_manager/contract_templates/form_service.py`
- `isrc_manager/contract_templates/export_service.py`

Pre-implementation mismatch that was closed in this pass:

- schema/service already carried more party data than the UI exposed
- the Party Manager editor only round-tripped a small legacy subset
- contract-template party placeholders were still limited to the older party field surface
- alias support did not exist as a user-manageable authority source for templates

## Fields Confirmed Vs Added

Confirmed/reused existing party fields:

- `legal_name`
- `display_name`
- `contact_person`
- `email`
- `phone`
- `website`
- `address_line1`
- `address_line2`
- `city`
- `region`
- `postal_code`
- `country`
- `tax_id`
- `vat_number`
- `pro_affiliation`
- `ipi_cae`
- `notes`
- `profile_name`

Added/expanded in the canonical party model:

- `artist_name`
- `company_name`
- `first_name`
- `middle_name`
- `last_name`
- `alternative_email`
- `street_name`
- `street_number`
- `bank_account_number`
- `chamber_of_commerce_number`
- `pro_number`
- `artist_aliases` via `PartyArtistAliases`

Practical field mapping rule:

- `legal_name` stays the canonical legal identity anchor
- `display_name` stays the preferred public/default name when present
- `artist_name` is the canonical singular artist-facing name
- `artist_aliases` is the explicit plural alternate-name list

## Alias Model Chosen

Chosen model:

- one canonical `Parties` row per person/company
- one optional canonical singular `artist_name` on the party row
- zero-to-many aliases in `PartyArtistAliases`

Key behavior:

- `PartyArtistAliases.normalized_alias` is globally unique
- `PartyService.find_party_id_by_name(...)` now resolves aliases as authoritative matches
- `ensure_party_by_name(...)` reuses canonical parties through alias-aware lookup instead of creating duplicate records
- merges preserve alias lists and can promote a duplicate party’s canonical `artist_name` onto the surviving primary record when the primary lacks one

Template safety rule:

- this pass exposes `artist_aliases` as the plural placeholder field
- no singular `artist_alias` placeholder was introduced, because multiple aliases would be ambiguous without an explicit preferred-alias model

## Party Manager UI Changes

The Party Manager remains table/list anchored, but the editor is now structured and safe for the full party payload.

Editor structure:

- `Identity`
- `Artist Aliases`
- `Address`
- `Contact`
- `Business / Legal`
- `Notes`

Editor coverage now includes:

- identity fields for artist/company/person naming
- dedicated alias add/remove table
- structured street/address fields
- alternate email
- bank, VAT, Chamber, PRO, and IPI fields

Workspace-level Party Manager changes:

- search hint updated to reflect alias and expanded identifier search
- added party-type filter
- table remains compact, but now surfaces primary name, legal/company identity, preferred email, alias summary, and linked-record count

Important safety improvement:

- editing an existing modern party record through the Party Manager no longer clears unsurfaced fields

## Contract/License Placeholder Mapping Changes

`db.party.*` continues to resolve from `PartyService.fetch_party(...)`, so the authoritative chain is:

1. selected party id in the fill form
2. `PartyService.fetch_party(...)`
3. `ContractTemplateExportService._resolve_catalog_value(...)`

Added party placeholder entries:

- `{{db.party.artist_name}}`
- `{{db.party.artist_aliases}}`
- `{{db.party.company_name}}`
- `{{db.party.first_name}}`
- `{{db.party.middle_name}}`
- `{{db.party.last_name}}`
- `{{db.party.alternative_email}}`
- `{{db.party.street_name}}`
- `{{db.party.street_number}}`
- `{{db.party.bank_account_number}}`
- `{{db.party.chamber_of_commerce_number}}`
- `{{db.party.pro_number}}`

Existing `db.party.*` placeholders remain supported.

Selector behavior:

- all `db.party.*` placeholders still group into one selector-driven party control
- selector labels now fall back through `display_name -> artist_name -> company_name -> legal_name`
- export resolves the expanded party fields from the selected canonical party record

## Tests Added/Updated

Updated or added:

- `tests/test_work_and_party_services.py`
- `tests/test_repertoire_dialogs.py`
- `tests/contract_templates/test_catalog.py`
- `tests/contract_templates/test_form_generation.py`
- `tests/contract_templates/test_export_service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_31_32.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/test_repertoire_exchange_service.py`

Verified passing:

- `python3 -m py_compile ...` on changed runtime and test files
- `python3 -m unittest tests.test_work_and_party_services`
- `python3 -m unittest tests.test_repertoire_dialogs`
- `python3 -m unittest tests.database.test_schema_current_target tests.database.test_schema_migrations_31_32`
- `python3 -m unittest tests.contract_templates.test_catalog tests.contract_templates.test_form_generation tests.contract_templates.test_export_service`
- `python3 -m unittest tests.exchange.test_repertoire_exchange_service tests.test_legacy_license_migration_service`
- `python3 -m unittest tests.test_work_and_party_services tests.test_repertoire_dialogs tests.database.test_schema_current_target tests.database.test_schema_migrations_31_32 tests.contract_templates.test_catalog tests.contract_templates.test_form_generation tests.contract_templates.test_export_service tests.exchange.test_repertoire_exchange_service tests.test_legacy_license_migration_service tests.test_catalog_workflow_integration tests.test_quality_service`

Attempted but blocked by unrelated baseline issue:

- `python3 -m unittest tests.app.test_app_shell_workspace_docks tests.app.test_app_shell_startup_core`

Observed failure:

- `tests/app/_app_shell_support.py` expects `ISRC_manager.QStandardPaths`, but the imported app module in this environment does not expose that symbol. This did not originate from the Party Manager changes in this pass.

## Remaining Limitations / Follow-Up Recommendations

- track artist identity is still a separate legacy domain (`Artists` / `TrackArtists`); this pass does not collapse track artists into canonical parties
- no preferred-alias flag exists yet, so singular alias placeholders remain intentionally out of scope
- contract-role-aware party placeholders are still out of scope; `db.party.*` remains generic selected-party resolution
- repertoire exchange schema version was intentionally not bumped in this pass; import/export was expanded in a backward-compatible way instead
- party merge still favors the primary party’s non-alias metadata; only canonical artist-name promotion and alias preservation were added here

## Safe Pickup Instructions

Read these files first:

- `isrc_manager/parties/models.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/parties/dialogs.py`
- `isrc_manager/contract_templates/catalog.py`
- `isrc_manager/contract_templates/export_service.py`
- `isrc_manager/services/schema.py`

Invariants to preserve:

- `Parties` remains the single canonical source for reusable legal/commercial party identity
- alias ownership must remain unambiguous
- `db.party.*` export must resolve from `PartyService.fetch_party(...)`
- the Party Manager must stay list/table anchored, with richer editing in the dialog rather than a builder-style workspace redesign

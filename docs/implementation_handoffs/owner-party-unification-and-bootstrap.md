# Owner / Party Unification And Bootstrap

## Status And Scope

This pass unifies Owner identity under Party authority and removes the settings-backed duplicate owner identity model.

Scope:

- owner identity storage
- owner reads/writes in settings and contract-template owner placeholders
- single-owner enforcement
- owner reassignment safety
- empty-db / missing-owner bootstrap

This pass does not introduce a second onboarding framework or a broad account/profile system.

## Prior Duplicate Owner / Party Authority Found

Before this pass, owner identity existed in two parallel forms:

1. `Parties`
- canonical artist / company / legal identity records
- Party Manager and imports already created and used these records

2. settings-backed owner snapshot state
- `app_kv` stored `owner_*` fields such as legal name, display name, contact, address, bank, tax, and affiliation values
- `BTW` and `BUMA_STEMRA` singleton tables also acted like owner-registration storage
- Application Settings exposed this as a separate editable owner namespace

That created conflicting identity authority:

- imported artists could exist as Party records while owner identity still lived elsewhere
- owner reads in contract templates and other settings-backed surfaces could drift away from Party
- switching owner identity risked duplicating the same person/company instead of reusing the Party record

## Final Single-Authority Model

Party is now the single source of truth for owner identity data.

The final model is:

- personal/legal/business identity fields live only on `Parties`
- the current owner is identified by a singleton binding in `ApplicationOwnerBinding`
- owner-facing reads resolve through the bound Party record
- legacy owner snapshot data is migration-only input, not continuing authority

`ApplicationOwnerBinding` is the app-level pointer to the current owner Party:

- one row only (`id = 1`)
- one bound `party_id`
- `party_id` is unique
- deleting the current owner Party is blocked until ownership is reassigned

## Owner Role / State Implementation

Owner is now a special Party-backed application role/state, not a separate identity namespace.

Implementation details:

- `SettingsReadService.load_owner_party_id()` now resolves the current owner through `ApplicationOwnerBinding`
- `SettingsReadService.load_owner_party_settings()` now returns Party-backed owner data only
- `SettingsMutationService.set_owner_party_id()` now updates the singleton owner binding and clears legacy `owner_*` snapshot keys
- `PartyService.delete_party()` now blocks deletion of the current owner Party
- `PartyService.merge_parties()` now rebinds the owner pointer when the current owner Party is merged into another Party

Party Manager now exposes owner state directly:

- an `Owner` column marks the current owner
- `Set As Owner` reassigns ownership to the selected Party

## Application Settings Changes

Application Settings no longer owns editable owner identity data.

Changes made:

- the Owner tab is now a selector/reference surface
- owner detail fields are read-only and mirror the selected current owner Party
- registration displays (`VAT`, `PRO`, `IPI/CAE`) are read from the owner Party
- saving settings now persists only `owner_party_id`, not a second copy of owner legal/contact identity fields
- contract-template owner wording now points to `Current Owner Party` instead of `Application Settings > Owner Party`

This keeps Settings usable without leaving it as a second authority.

## First-Launch / Missing-Owner Bootstrap

The app now enforces owner bootstrap for normal usable state.

Behavior:

- on database open, legacy owner snapshot data is migrated into Party authority when needed
- after startup becomes ready, the app schedules owner bootstrap if no current owner Party exists
- profile activation also schedules the same owner bootstrap if the selected profile has no owner
- `OwnerBootstrapDialog` forces the user to create or choose a Party and assign it as Owner
- the dialog does not offer a normal cancel path; it loops until an owner Party is assigned

This keeps the app from remaining in a normal operational state without an owner.

## Legacy Snapshot Migration

Legacy owner snapshot state is still recognized only for migration and cleanup.

Migration behavior:

- if a current owner Party already exists, blank Party fields can be backfilled from legacy owner snapshot data
- if no owner Party exists, the app tries:
  - linked `party_id`
  - deterministic Party name matches
  - otherwise creation of a new Party from the legacy snapshot
- after successful migration, legacy `owner_*` snapshot keys are cleared
- legacy `BTW` / `BUMA_STEMRA` owner-registration rows are cleared once the owner Party is established

## Tests Added / Updated

Updated:

- `tests/test_settings_read_service.py`
- `tests/test_settings_mutations_service.py`
- `tests/test_work_and_party_services.py`
- `tests/test_theme_builder.py`
- `tests/test_repertoire_dialogs.py`
- `tests/contract_templates/test_catalog.py`
- `tests/contract_templates/test_form_generation.py`
- `tests/contract_templates/test_export_service.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_startup_core.py`

Coverage added/updated for:

- Party-backed owner reads
- legacy owner snapshot migration reads
- singleton owner binding writes
- owner registration writes landing on the bound Party
- deletion guard for the current owner Party
- owner rebinding during Party merges
- Application Settings using owner Party reference instead of duplicate authority
- Party Manager owner marking and reassignment
- startup bootstrap requiring owner assignment before normal use
- contract-template owner placeholders resolving from Current Owner Party

## Files Changed

- `ISRC_manager.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/settings_reads.py`
- `isrc_manager/services/settings_mutations.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/parties/dialogs.py`
- `isrc_manager/history/manager.py`
- `isrc_manager/contract_templates/catalog.py`
- `isrc_manager/contract_templates/models.py`
- `isrc_manager/contract_templates/form_service.py`
- `isrc_manager/contract_templates/export_service.py`
- `isrc_manager/contract_templates/dialogs.py`
- related tests listed above

## Risks / Caveats

- schema-level enforcement is a singleton owner binding plus service guards; this pass does not add a broad Party-role table
- legacy `owner_*` snapshot reads still exist for migration helpers, but they are no longer the continuing owner authority
- startup/profile tests suppress the modal bootstrap by default and exercise it explicitly in focused coverage, to keep unrelated shell tests deterministic

## Explicit Final Statement

Party is now the single source of truth for owner identity data.

New and existing owner-facing reads resolve from the current owner Party, owner data is no longer stored twice as an active authority model, and the app now requires a Party to be assigned as Owner before normal use can continue.

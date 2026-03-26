# Party Import / Export Parity

## Status And Scope

This pass adds first-class Party import and export with the same overall lifecycle quality as the app's existing exchange flows:

- selected vs full export
- inspect before import
- field mapping
- source preview
- safe create/update matching
- background-task execution with history logging

The scope stays specific to canonical `Parties`.
It does not add a second identity model and it does not repurpose the broad contracts-and-rights bundle workflow as the primary Party UX.

## Existing Import / Export Patterns Audited

The reusable source patterns were:

- `Catalog Exchange`
  - supported import: `XML`, `CSV`, `XLSX`, `JSON`, `ZIP package`
  - supported export: selected/full `XML`, `CSV`, `XLSX`, `JSON`, `ZIP package`
  - strongest reusable lifecycle: inspect -> review/map -> execute -> report
- `Contracts and Rights`
  - supported import/export: `JSON`, `XLSX`, `CSV bundle`, `ZIP package`
  - useful for format parity reference, but it does not have the richer mapping/review UI

The Party feature now follows the richer catalog-exchange style because that was the closest parity fit for Party-domain data.

## Formats Supported For Parties

Party import/export now supports:

- `CSV`
- `XLSX`
- `JSON`

These are the relevant formats already proven by analogous app workflows and they fit Party rows cleanly.

Formats intentionally not added for Party import/export in this pass:

- `XML`
  - audio-catalog specific
- `ZIP package`
  - Party rows do not carry packaged media/document payloads the way catalog/package exchanges do
- `CSV bundle`
  - unnecessary for a single-entity Party catalog

## Party Export Behavior

Export now exists in two scopes:

- selected Party rows
- full Party catalog

Launch points:

- `File > Export > Parties`
- `Party Manager > Import and Export`

Supported export actions:

- `Export Selected Parties CSV…`
- `Export Selected Parties XLSX…`
- `Export Selected Parties JSON…`
- `Export Full Party Catalog CSV…`
- `Export Full Party Catalog XLSX…`
- `Export Full Party Catalog JSON…`

Export structure is round-trip-friendly and includes canonical Party fields plus:

- `id`
- `artist_aliases`
- `is_owner`
- `profile_name`

`artist_aliases` are serialized as structured JSON lists in tabular exports so aliases survive round-trip safely.

## Party Import Behavior

Party import now uses a Party-specific mapping/review dialog that mirrors the catalog exchange workflow:

- `Setup & Mapping` tab
- `Source Preview` tab
- mapping presets
- remembered import choices per format
- CSV delimiter reinspection
- dry-run validation before commit

Launch points:

- `File > Import & Exchange > Parties`
- `Party Manager > Import and Export`

Supported import actions:

- `Import Parties CSV…`
- `Import Parties XLSX…`
- `Import Parties JSON…`

Import modes:

- `dry_run`
- `create`
- `update`
- `upsert`
- `merge`

Mode behavior:

- `dry_run`
  - validates mappings and safe matching only
  - writes nothing
- `create`
  - creates only new Parties
  - safe matches are skipped as duplicates
- `update`
  - updates only rows with one safe existing Party match
  - unmatched rows are skipped
- `upsert`
  - creates when no safe match exists
  - otherwise updates the matched Party with imported non-empty values
- `merge`
  - creates when no safe match exists
  - otherwise fills only missing values and unions aliases onto the matched Party

## Party Mapping Rules

The supported import/export targets are tuned to the Party schema:

- `legal_name`
- `display_name`
- `artist_name`
- `artist_aliases`
- `company_name`
- `first_name`
- `middle_name`
- `last_name`
- `party_type`
- `is_owner`
- `contact_person`
- `email`
- `alternative_email`
- `phone`
- `website`
- `street_name`
- `street_number`
- `address_line1`
- `address_line2`
- `city`
- `region`
- `postal_code`
- `country`
- `bank_account_number`
- `chamber_of_commerce_number`
- `tax_id`
- `vat_number`
- `pro_affiliation`
- `pro_number`
- `ipi_cae`
- `notes`
- `profile_name`

The mapper also recognizes common header aliases such as:

- `Legal Name`
- `Display Name`
- `Artist Name`
- `Artist Aliases`
- `Email Address`
- `Alternative Email Address`
- `Phone Number`
- `VAT / BTW Number`
- `Chamber of Commerce Number`
- `PRO Number`
- `IPI / CAE`
- `Owner`

If `legal_name` is blank during create/import, the importer safely seeds it from the best available identity field:

- `display_name`
- `artist_name`
- `company_name`
- structured person name
- `email`

That fallback is reported as a warning so the user can see that normalization happened.

## Create / Update / Match Rules

The new Party importer is identity-safe by design.

Enabled matching rules can use:

- internal `id`
- exact `legal_name`
- identity keys
  - `email`
  - `alternative_email`
  - `chamber_of_commerce_number`
  - `pro_number`
  - `ipi_cae`
- exact Party-facing name fields
  - `display_name`
  - `artist_name`
  - `company_name`
  - full person name
  - exact normalized artist aliases

Safety behavior:

- matching rules are intersected conservatively
- if the enabled rules collapse to one Party, that match is accepted
- if they point to multiple Parties or conflict, the row fails
- the importer does not silently guess a risky merge target

Update semantics:

- `upsert`
  - imported non-empty values replace existing values
  - blank imported cells do not silently clear Party data
- `merge`
  - existing non-empty values win
  - imported non-empty values fill gaps only
  - aliases are unioned safely

Owner-role integrity:

- Party export surfaces `is_owner`
- Party import accepts `is_owner` safely
- at most one imported row may request current-owner reassignment in one run
- if multiple rows request owner reassignment, those owner rows fail and no owner binding is changed

## Workflow Integration

Party import/export is now integrated in both places users expect:

- `File > Import & Exchange > Parties`
- `File > Export > Parties`
- `Party Manager`
  - `Import…`
  - `Export Selected…`
  - `Export All…`

The Party Manager buttons open format menus for `CSV`, `XLSX`, and `JSON`, while the app-level file menus expose direct format-specific actions.

Imports and exports run through the existing background-task and history infrastructure.

## Tests Added / Updated

Added:

- `tests/test_party_exchange_service.py`
- `tests/test_party_import_dialog.py`

Updated:

- `tests/test_repertoire_dialogs.py`
- `tests/app/_app_shell_support.py`

Covered behavior includes:

- selected Party export
- full Party catalog export
- CSV import
- XLSX import
- JSON import
- field mapping and preview dialog behavior
- CSV delimiter reinspection and validation
- safe create/update behavior
- ambiguous-match rejection
- owner-role import integrity
- Party Manager import/export menus
- File menu import/export menu wiring

Validation run:

- `python3 -m unittest tests.test_party_exchange_service`
- `python3 -m unittest tests.test_party_import_dialog`
- `python3 -m unittest tests.test_repertoire_dialogs`
- `python3 -m unittest tests.app.test_app_shell_startup_core`
- `python3 -m black --check ISRC_manager.py isrc_manager/main_window_shell.py isrc_manager/parties/__init__.py isrc_manager/parties/dialogs.py isrc_manager/parties/exchange_service.py isrc_manager/parties/service.py isrc_manager/tasks/app_services.py tests/test_party_exchange_service.py tests/test_party_import_dialog.py tests/test_repertoire_dialogs.py tests/app/_app_shell_support.py`

## Risks / Caveats

- Party import currently treats multiple owner-assignment rows conservatively by failing those owner rows instead of guessing which Party should become the current Owner.
- `legal_name` is still the canonical required Party field at the service level, so imports with no usable identity field still fail rather than inventing unusable Party rows.
- This pass intentionally did not broaden the contracts-and-rights bundle importer into a first-class Party mapping workflow; it left that broad bundle path intact and added a dedicated Party flow instead.
- The existing generic `PartyEditorDialog` still does not expose `profile_name` directly; this pass preserves `profile_name` during Party exchange, but it does not redesign manual Party editing around that field.

## Explicit Outcome

Party import/export now has parity with the app’s existing import/export model:

- Party export exists for selected rows and full catalog
- Party import exists with mapping, preview, review, and report behavior
- supported formats are aligned to the app’s relevant tabular/json exchange formats
- Party identity authority is preserved
- Party Manager now has a native Party import/export workflow instead of relying on broad repertoire bundle paths

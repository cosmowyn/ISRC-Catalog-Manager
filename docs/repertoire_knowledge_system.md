# Repertoire Knowledge System

This document summarizes the extended local-first model that sits on top of the existing track, release, license, GS1, media, and exchange layers.

## Product Intent

The application now aims to be a complete indie catalog manager for artists and labels.

It is intentionally:

- local-first
- SQLite-backed
- desktop-native with PySide6
- focused on repertoire, rights, contracts, parties, documents, and deliverables

It is intentionally not:

- a royalty accounting platform
- a payment/distribution integration layer
- a DSP/release-pitching workflow tool

## Core Entities

### Work

A `Work` is the composition/songwriting layer and stays separate from recordings.

Key fields:

- title
- alternate titles
- subtitle/version
- language
- lyrics/instrumental flags
- genre/style notes
- ISWC
- local registration number
- workflow status and checklist flags
- notes

Relationships:

- `WorkContributors`
- `WorkTrackLinks`
- contract links
- rights links

### Party

A `Party` is the reusable person/company/contact registry.

Key fields:

- legal/display name
- party type
- contact details
- location/tax/PRO/IPI metadata
- notes

Relationships:

- work contributors
- contract parties
- rights holders / grantors / grantees

### Contract

A `Contract` is a lifecycle-aware agreement record.

Key fields:

- contract type
- draft/signature/effective/start/end/renewal/notice/reversion/termination dates
- supersedes / superseded-by
- status
- summary/notes

Relationships:

- `ContractParties`
- `ContractObligations`
- `ContractDocuments`
- works
- tracks
- releases
- source rights grants

Legacy note:

- the older `Licenses` + `Licensees` tables still exist as the lightweight track-level PDF archive
- `Catalog > Migrate Legacy Licenses to Contracts...` promotes those legacy records into `Parties`, `Contracts`, and `ContractDocuments`
- the migration is explicit and checksum-verified; it does not silently reinterpret old data on profile open

### RightsRecord

A `RightsRecord` stores a specific rights grant or retained control position.

Key fields:

- right type
- exclusive flag
- territory
- media/use type
- start/end/perpetual
- granted by / granted to / retained by
- source contract
- linked work / track / release

### AssetVersion

An `AssetVersion` stores one managed deliverable or artwork variant.

Key fields:

- asset type
- managed file reference
- checksum
- duration / sample rate / bit depth where available
- derived-from relationship
- approved-for-use
- primary flag
- version status

## Navigation

Two services make the richer model navigable:

- `GlobalSearchService`
- `RelationshipExplorerService`

They work across:

- works
- tracks
- releases
- contracts
- rights
- parties
- contract documents
- asset versions

## Workflow State

Tracks and releases now carry additive workflow/checklist columns:

- `repertoire_status`
- `metadata_complete`
- `contract_signed`
- `rights_verified`

Works carry:

- `work_status`
- `metadata_complete`
- `contract_signed`
- `rights_verified`

Derived readiness flags, such as audio attached, artwork present, work linked, and creator linked, are surfaced through `RepertoireWorkflowService`.

## Quality Coverage

The quality dashboard now includes:

- works without creators
- invalid split totals
- duplicate ISWC
- contracts near notice deadlines
- contracts missing signed final documents
- active contracts without linked assets
- rights missing source contracts
- overlapping exclusive rights
- duplicate parties
- tracks missing linked works where composition metadata exists
- broken asset references
- missing approved master
- blocked or incomplete repertoire items

## Exchange

The regular track/release exchange service is unchanged.

A separate `RepertoireExchangeService` now handles:

- parties
- works
- contracts
- rights
- asset versions
- relationship references

Supported formats:

- JSON
- XLSX
- CSV bundle directory
- ZIP package with manifest plus managed contract/asset files

## Migration Strategy

The repertoire expansion is additive and preserves older workspaces:

- existing track/release/license rows are not reinterpreted destructively
- new tables are created only if missing
- workflow columns are appended to existing `Tracks` and `Releases`
- foreign keys stay explicit
- old databases remain valid even if no work/contract/right data exists yet

Legacy license migration strategy:

- legacy license rows can remain in place for users who prefer the simpler PDF archive workflow
- a dedicated migration action copies each managed legacy PDF into `contract_documents`
- the migrated document checksum is verified against the original managed file before cleanup
- related `Party` records are created or reused from legacy `Licensees`
- related `Work` and `Release` links are inferred from the original track where possible
- legacy `Licenses`, `Licensees`, and old managed license files are removed only after verification succeeds
- before/after history snapshots are recorded so the whole migration can be undone or redone safely

## Package Layout

New packages introduced by this layer:

- `isrc_manager.parties`
- `isrc_manager.works`
- `isrc_manager.contracts`
- `isrc_manager.rights`
- `isrc_manager.assets`
- `isrc_manager.search`

Additional service entrypoints added on top of the original service layer:

- `LegacyLicenseMigrationService`
- expanded `HistoryManager` snapshot coverage for repertoire tables and managed directories

These packages follow the same pattern already used elsewhere in the project:

- dataclass models
- focused services
- thin dialogs
- additive schema migrations

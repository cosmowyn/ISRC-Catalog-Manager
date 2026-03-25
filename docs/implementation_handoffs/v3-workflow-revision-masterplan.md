# V3 Workflow Revision Masterplan

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status

Phase 0 is complete.

This master plan records the v3 workflow revision grounded in the live repository and the Phase 0 characterization pass.

Important scope notes:

- `3.0.0` is a workflow-shaping release, not a cosmetic pass
- `Work` becomes the parent governance entity
- `Track` remains the child governed product entity
- `Catalog` remains the operational inventory and execution surface
- `Party` becomes the default identity authority
- legacy license architecture is planned for removal, not preservation
- backward compatibility with older databases is not the priority for this revision
- Phase 0 lands documentation and characterization only; broad runtime behavior changes begin in Phase 1

## Source Of Truth

This master plan was built from:

- the live repository state on branch `v3`
- the user instruction dated 2026-03-25
- previously reconciled planning-wave findings under the 6-worker cap
- Phase 0 implementation helpers used for doc QA and characterization-test confirmation
- the existing implementation-handoff style already established in `docs/implementation_handoffs/`

Primary repo surfaces:

- `ISRC_manager.py`
- `isrc_manager/main_window_shell.py`
- `isrc_manager/catalog_workspace.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/works/*`
- `isrc_manager/parties/*`
- `isrc_manager/contracts/*`
- `isrc_manager/rights/*`
- `isrc_manager/quality/service.py`
- `isrc_manager/exchange/service.py`
- `tests/test_track_service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_package.py`
- `tests/test_catalog_workflow_integration.py`

Relevant prior handoffs and guides:

- `docs/implementation_handoffs/backlog-unified-implementation-strategy.md`
- `docs/implementation_handoffs/catalog-workspace-ui-followup.md`
- `docs/implementation_handoffs/party-manager-expansion-and-template-binding.md`
- `docs/implementation_handoffs/derivative-ledger-workspace-cleanup.md`

## Product Framing

### What v3 is trying to become

`3.0.0` is a coherence pass that reshapes the application around one governed workflow:

- `Work Manager` is the parent governance entry point
- `Track` records are the governed child products created under a `Work`
- `Catalog Table` remains the operational inventory, search, batch, and execution surface
- `Party Manager` becomes the authoritative identity layer for people, companies, and legal entities
- contracts, rights, templates, and future ecosystem outputs resolve from authoritative `Party`, `Work`, `Track`, and agreement data

### What v3 is explicitly not

`3.0.0` is not:

- a track-first workflow with optional later governance
- a product where `Work` and `Catalog` remain confusing parallel peers
- a single vague rights model that collapses composition ownership, recording ownership, and contribution roles
- a free-text identity system for legal or payout-bearing entities
- a legacy-license preservation pass

## Repo-Grounded Baseline

Phase 0 confirmed the following about the current repository:

- `TrackService.create_track()` creates tracks directly in `Tracks` and stores composition-adjacent fields like `buma_work_number`, `iswc`, `composer`, and `publisher` on the track row.
- Current track creation does not automatically create or link a `Work`; `tests/test_track_service.py` now characterizes that track creation succeeds even with no `Works` table present.
- `WorkService` and `WorkTrackLinks` already exist, but `Work` is not yet the default parent-governance creation flow.
- `CatalogReadService.fetch_rows_with_customs()` and `find_album_metadata()` read directly from `Tracks`, `Artists`, and `Albums`, which means catalog inventory is still track-row centric.
- `QualityDashboardService._license_issues()` queries `Licenses` directly and emits `orphaned_license`.
- `ExchangeService._license_map()` still queries `Licenses` directly and exports `license_files`.
- `PartyService`, `ContractService`, `RightsService`, and `WorkService` already exist, but identity-bearing flows are still mixed between structured party links and free-text names.
- Quality and workflow tests already expose the current fragmentation, including `track_missing_linked_work` in `tests/test_catalog_workflow_integration.py`.

This baseline is intentionally frozen by Phase 0 characterization tests so later phases can remove or reroute these dependencies deliberately instead of accidentally.

## Shared Invariants And Non-Goals

The following must remain true throughout the v3 revision:

- the live repository is the only source of truth for implementation decisions
- `Work` is the parent governance entity
- `Track` is the governed child entity
- `Catalog` stays the operational inventory and execution surface
- identity-bearing fields should resolve to `Party` by default
- work ownership, recording/master ownership, and contribution roles remain separate concerns
- no phase should preserve obsolete license pathways just for sentimental backward compatibility
- no phase should silently rewrite neighboring systems without an updated handoff
- no more than 6 helper agents may exist concurrently
- idle workers must be closed once their findings are reconciled

Non-goals for this revision:

- preserving old database compatibility at any cost
- keeping free-text legal identity fields as the default UX
- leaving `Work Manager` and `Catalog` conceptually redundant
- treating `WorkTrackLinks` as the long-term governing model if a cleaner parent-child shape is available

## Proposed V3 Workflow Architecture

### 1. Product Workflow Architecture

Primary product shape:

- `Work Manager` becomes the main creation and governance entry point
- new governed tracks are normally created from inside a `Work`
- later versions, remixes, alternate masters, edits, live versions, and derivatives are also added from the parent `Work`
- `Catalog Table` remains the operational surface for browse, search, filter, triage, batch edit, reassignment, export, and admin actions
- `Party Manager` becomes the default identity authority for any person, company, label, publisher, administrator, or rights holder
- contracts, rights records, templates, and downstream outputs consume authoritative data instead of duplicating identity and governance logic

### 2. Domain Model Cleanup

#### `Work`

`Work` becomes the authoritative home for:

- composition title and alternate titles
- `iswc`
- work status and governance completeness
- composition-side metadata and parent-work relationships
- writers, publishers, and work ownership interests
- composition-side contribution entries where that distinction matters
- the set of governed child tracks

#### `Track`

`Track` remains the authoritative home for:

- recording-facing metadata
- release-facing fields
- media references
- recording/master contribution entries
- sound recording and master ownership interests

Planned v3 governance additions on `Track`:

- `work_id`
- `parent_track_id`
- `relationship_type`

Expected relationship values:

- `original`
- `version`
- `remix`
- `edit`
- `live`
- `instrumental`
- `alternate_master`
- `other`

#### Ownership And Contribution Layers

V3 explicitly separates:

- `WorkOwnershipInterests`
  - authorship
  - publishing
  - composition-share governance
- `RecordingOwnershipInterests`
  - master ownership
  - label ownership
  - recording-rights holder data
- `WorkContributionEntries`
  - songwriting and composition-side roles that are not the same thing as ownership
- `RecordingContributionEntries`
  - producer
  - mixer
  - mastering engineer
  - remixer
  - performers
  - engineers
  - other recording-side roles

#### `Party`

`Party` becomes the identity authority for:

- legal names
- display names and aliases
- companies versus individuals
- contract parties
- rights grantees
- work owners
- recording/master owners
- credited contributors where identity matters

Identity-bearing relations should store `party_id` first. Free text becomes optional credited or display text, not the governing storage model.

#### Linked Tracks, Versions, And Remixes

Planned v3 direction:

- one governing `Work` per `Track` as the default model
- one parent track when a child relationship is needed
- typed child relationships for versions, remixes, edits, live cuts, and alternate masters
- `WorkTrackLinks` stops being the governing relationship and is either deprecated or narrowed to non-governing reference links such as `sample_of` or `adaptation_of`

### 3. Workflow Changes

#### New work creation

Default flow:

1. create a new `Work`
2. capture work metadata and initial governance data
3. offer immediate creation of the first child `Track`
4. persist the parent-child relationship at creation time

#### First-track creation

The first-track flow should:

- start from the `Work` context
- seed eligible track fields from the parent work where useful
- create the parent-child relationship immediately
- avoid silently overwriting work data when the track is later edited

#### Later versions and derivatives

Future child flows should support:

- add version
- add remix
- add alternate master
- add edit
- add live version
- add derivative or other child type

These flows should remain inside the parent `Work` context unless the user is handling imported or orphaned rows from `Catalog`.

#### Catalog behavior

The catalog remains responsible for:

- browse and search
- filter and sort
- bulk edit
- inventory visibility
- assignment and reassignment of imported or orphaned tracks
- operational execution and admin actions

It should no longer be the conceptual first stop for creating governed products.

### 4. UI Restructuring

#### `Work Manager`

V3 `Work Manager` should hold structured tabs or sections for:

- `Overview`
- `Composition / Work Metadata`
- `Writers / Publishers / Work Ownership`
- `Recording / Master Ownership`
- `Contributions / Roles`
- `Linked Tracks / Versions`
- `Contracts / Rights Links`

#### `Catalog`

V3 `Catalog` should:

- keep track inventory visible and editable
- absorb recording-focused operational functions that do not need to live in `Work Manager`
- keep bulk edit and track edit strong for product operations
- expose repair/admin paths for orphaned imports without making them the default workflow

#### Duplicate actions

Planned cleanup:

- de-emphasize or remove floating track creation as the main route
- make `Add Track` creation-only and work-context aware
- remove duplicate identity entry surfaces when a `Party` selector should own the field
- avoid keeping work-governance editing split awkwardly between `Work Manager` and `Catalog`

### 5. Legacy Removal Plan

Legacy license direction:

- remove `Licensees`
- remove `Licenses`
- remove `vw_Licenses`
- remove `LicenseService`
- remove the legacy license migration service and its UI/admin surface
- remove license-specific menu, browser, and admin routes that contradict the v3 product shape

Schema cleanup direction:

- stop treating track-level composition fields as the long-term authoritative home for work governance
- replace generic or collapsed rights constructs where they currently hide ownership distinctions
- narrow `RightsRecords` so each row has one clear scope and stays downstream of agreements and ownership
- drop compatibility shims when the cleaner v3 model is ready

## Phase Map

### Phase 0. Master Strategy, Characterization, And Continuity

Goal:

- define the v3 architecture
- write the master and phase handoffs
- reserve the future handoff chain
- add characterization coverage around track-first, catalog-read, and legacy-license dependencies

Dependencies:

- none

Acceptance boundary:

- `docs/implementation_handoffs/v3-workflow-revision-masterplan.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-0.md`
- `docs/implementation_handoffs/v3-workflow-revision-planning-wave-1-checkpoint.md`
- placeholder handoffs for Phases 1 through 5
- characterization tests landed without runtime workflow changes

Deferred items:

- all major product-shaping runtime changes

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-0.md`

### Phase 1. Party Authority Cutover

Goal:

- make identity-bearing workflow paths Party-first

Dependencies:

- Phase 0

Acceptance boundary:

- owner and legal-entity identity resolution becomes Party-first across work, contract, rights, and template-facing surfaces
- selector-first and quick-create party flows are identified and landed on the targeted surfaces

Deferred items:

- full Work-parent governance and legacy-license deletion

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-1.md`

### Phase 2. Domain Model Revision

Goal:

- revise the work/track/ownership/contribution model toward the v3 parent-child shape

Dependencies:

- Phase 1

Acceptance boundary:

- one governing work per track becomes enforceable in the current-target model
- typed child-track lineage exists
- ownership and contribution layers stop collapsing into one vague concept

Deferred items:

- final catalog projection cleanup

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`

### Phase 3. Work Manager Expansion And Creation Rewrite

Goal:

- make `Work Manager` the default parent-governance creation surface

Dependencies:

- Phase 2

Acceptance boundary:

- create work plus first-track flow exists
- later child-track flows live in work context
- work governance tabs and sections are expanded into the intended v3 shape

Deferred items:

- final catalog inventory projection cleanup

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-3.md`

### Phase 4. Catalog Integration And Inventory Cleanup

Goal:

- keep `Catalog` strong as the operational inventory while reducing governance duplication

Dependencies:

- Phase 3

Acceptance boundary:

- search, quality, export, and operational catalog reads derive governance and identity from authoritative work/party/contract/rights data
- redundant governance surfaces are reduced
- track edit and bulk edit remain recording-focused

Deferred items:

- full legacy-license deletion and final shell cleanup

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`

### Phase 5. Legacy Removal And Final V3 Shell Cleanup

Goal:

- remove obsolete legacy-license paths and align the shell to the final v3 workflow

Dependencies:

- Phase 4

Acceptance boundary:

- no production codepath reads `Licensees`, `Licenses`, or `vw_Licenses`
- obsolete duplicate actions are removed or demoted
- the shell, menus, and docs match the v3 product shape

Deferred items:

- only clearly documented post-v3 polish or bug follow-up

Handoff path:

- `docs/implementation_handoffs/v3-workflow-revision-phase-5.md`

## Dependencies And Ordering Constraints

- Phase 1 should land before major governance-model surgery so identity-bearing relations do not multiply again during the v3 cutover
- Phase 2 should land before the full Work Manager workflow rewrite so the UI is built on the intended parent-child model instead of on temporary shims
- Phase 3 should land before Phase 4 so catalog cleanup can consume the new work-governance model instead of inventing another one
- Phase 4 should land before Phase 5 so export, search, and quality pathways no longer depend on legacy license tables when those tables are removed
- schema cleanup that breaks old databases is acceptable, but it should be done deliberately and documented honestly at the phase boundary that introduces it

## Test Strategy

Structural validation:

- schema current-target tests for work-parent and track-child relationships
- Party-first identity invariants
- single-scope rights-record validation
- explicit ownership and contribution table coverage
- removal of direct legacy-license reads when the cleanup phase arrives

Workflow validation:

- create work and optionally create first track immediately
- add version, remix, alternate master, or other child tracks under an existing work
- assign or reassign imported/orphaned catalog rows into a work
- edit track data without mutating work data silently
- quick-create Party from work, contract, and rights selectors
- verify downstream contract/template resolution from authoritative data

Regression boundaries:

- catalog reads and catalog search
- quality dashboard behavior
- exchange import and export
- workspace docking, startup, layout persistence, and app-shell menu behavior
- one end-to-end pass through catalog, work, contract, rights, and search surfaces

Phase 0 characterization landed here:

- `tests/test_track_service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_package.py`

## Continuity And Handoffs

Master handoff:

- `docs/implementation_handoffs/v3-workflow-revision-masterplan.md`

Temporary planning checkpoint:

- `docs/implementation_handoffs/v3-workflow-revision-planning-wave-1-checkpoint.md`

Per-phase handoffs:

- `docs/implementation_handoffs/v3-workflow-revision-phase-0.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-1.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-3.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-5.md`

Pause and resume rules:

- no phase is complete without its handoff
- if work stops mid-phase, the current phase doc should be marked `in_progress` or `blocked`
- resume by reading the master plan first, then the latest phase handoff, then any newer follow-up notes
- rerun the smallest validation set named in the latest handoff before continuing

Every completed phase handoff must include:

- phase goal
- what changed
- source-of-truth files and surfaces
- files changed
- tests added or updated
- validation performed
- deferred items
- risks and caveats
- workers used and workers closed
- QA/QC summary
- exact safe pickup instructions

## QA/QC Baseline

Central-oversight quality gates for the v3 revision:

- `Work` stays the parent governance entity
- `Catalog` remains the operational inventory rather than a competing product concept
- Party-driven identity resolution keeps replacing free-text identity drift
- ownership layers remain separated instead of collapsing back into generic rights blobs
- track creation becomes child-first by design, not by convention
- legacy license logic is removed intentionally only after replacement pathways are ready
- no more than 6 concurrent helper agents exist at any time

## Important Continuation Notes

- Phase 0 documents the intended v3 architecture and the current baseline, but it does not land the architectural cutover itself
- `TrackService.create_track()` still reflects the old track-first world; later phases must change that deliberately, not incidentally
- direct reads from `Licenses` remain present in quality and exchange codepaths today; do not pretend they are already abstracted away
- the app already contains reusable `Work`, `Party`, `Contract`, and `Rights` seams, so later phases should extend those seams instead of adding another parallel governance subsystem
- forward correctness takes priority over historical database compatibility in this revision

## Related Handoffs

- `docs/implementation_handoffs/v3-workflow-revision-planning-wave-1-checkpoint.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-0.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-1.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-3.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-5.md`

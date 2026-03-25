# V3 Workflow Revision Phase 2

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 2 is `in_progress`.

This first runtime slice lands the domain-model foundation only:

- `Track` now has direct governing fields for `work_id`, `parent_track_id`, and `relationship_type`
- `WorkTrackLinks` is still present, but only as a synchronized compatibility shadow for current read-side consumers
- explicit ownership and contribution ledger tables now exist in schema
- explicit work-ownership and recording-ownership service flows now exist in `RightsService`

Phase 2 is not complete yet. UI restructuring, creation-flow rewrite, and read-side authority cutovers remain deferred to later slices.

## Phase Goal

Revise the domain model toward a parent `Work`, child `Track`, and explicitly separated ownership and contribution architecture.

## What Changed

The first Phase 2 runtime landing is now in place.

- bumped schema target from `32` to `33`
- added `Tracks.work_id`, `Tracks.parent_track_id`, and `Tracks.relationship_type`
- added schema tables:
  - `WorkOwnershipInterests`
  - `RecordingOwnershipInterests`
  - `WorkContributionEntries`
  - `RecordingContributionEntries`
- added migration `32 -> 33`
- migration backfills `Tracks.work_id` from legacy `WorkTrackLinks`
- migration normalizes `relationship_type` to `original` when blank
- migration mirrors legacy `WorkContributors` rows into `WorkContributionEntries`
- migration deduplicates `WorkTrackLinks` down to one governing work per track and adds a unique index on `track_id`
- `TrackService` now persists and snapshots governance fields when the schema supports them
- `TrackService.update_track()` preserves existing governance values when older callers do not pass any governance fields
- `TrackService` keeps `WorkTrackLinks` synchronized as a shadow bridge when `work_id` changes
- `WorkService` now writes governing `Tracks.work_id` state when linking or unlinking tracks to a work
- `WorkService` mirrors work contributors into `WorkContributionEntries`
- `PartyService.merge_parties()` now updates the new ownership and contribution tables so Party authority does not drift
- `RightsService` now exposes explicit ownership-ledger CRUD for:
  - `WorkOwnershipInterests`
  - `RecordingOwnershipInterests`
- `RightsService.ownership_summary()` now prefers the explicit ownership ledgers before falling back to inferred grant rows
- track ownership summaries now resolve publishing control from the linked governing work when explicit work-ownership interests exist

## Source Of Truth Files And Surfaces

Active Phase 2 source-of-truth surfaces for this slice:

- `isrc_manager/constants.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/works/service.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/rights/models.py`
- `isrc_manager/rights/service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_32_33.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/catalog/test_rights_service.py`
- `tests/test_track_service.py`
- `tests/test_work_and_party_services.py`

## Files Changed

- `isrc_manager/constants.py`
- `isrc_manager/services/schema.py`
- `isrc_manager/services/tracks.py`
- `isrc_manager/works/service.py`
- `isrc_manager/parties/service.py`
- `isrc_manager/rights/__init__.py`
- `isrc_manager/rights/models.py`
- `isrc_manager/rights/service.py`
- `tests/database/_schema_support.py`
- `tests/database/test_schema_migrations_32_33.py`
- `tests/catalog/_contract_rights_asset_support.py`
- `tests/catalog/test_rights_service.py`
- `tests/test_track_service.py`
- `tests/test_work_and_party_services.py`
- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`

## Tests Added Or Updated

Added or updated coverage in this slice:

- current-target schema assertions now require the new governance columns and explicit interest/ledger tables
- new migration coverage for `32 -> 33`
- track-service coverage for:
  - governance persistence when schema support exists
  - preservation of governance values when legacy update callers omit them
- work-service coverage for:
  - `Tracks.work_id` assignment on work creation and unlink
  - work-contribution mirroring into `WorkContributionEntries`
  - reassignment to a new governing parent work
- rights-service coverage for:
  - explicit work-ownership ledger CRUD
  - explicit recording-ownership ledger CRUD
  - track ownership summaries driven by explicit ledgers instead of inferred grants only
- party-merge coverage for mirrored work-contribution updates
- party-merge coverage for explicit ownership-ledger rewrites

Validation run:

- `python3 -m unittest tests.database.test_schema_current_target tests.database.test_schema_migrations_31_32 tests.database.test_schema_migrations_32_33`
- `python3 -m unittest tests.test_track_service tests.test_work_and_party_services tests.test_repertoire_status_service tests.test_catalog_workflow_integration tests.test_quality_service`
- `python3 -m unittest tests.catalog.test_rights_service tests.test_work_and_party_services`
- `python3 -m unittest tests.database.test_schema_current_target tests.database.test_schema_migrations_31_32 tests.database.test_schema_migrations_32_33 tests.catalog.test_rights_service tests.test_track_service tests.test_work_and_party_services tests.test_repertoire_status_service tests.test_catalog_workflow_integration tests.test_quality_service`

## What Was Intentionally Deferred

- recording-side contribution service flows for `RecordingContributionEntries`
- narrowing `RightsRecords` to one scope per row
- work-manager UI expansion
- work-first creation flow and child-track creation UX
- catalog read-side authority cutover from `WorkTrackLinks` toward direct `Tracks.work_id`
- legacy license deletion

## Risks And Caveats

- `WorkTrackLinks` is still live for read-side consumers like quality, repertoire status, search, and some catalog paths; it is now a shadow bridge, not the intended final authority
- `TrackService.update_track()` currently treats omitted governance fields as “preserve current value”; explicit clearing from generic track-edit paths is intentionally deferred until governance-specific UI exists
- the new ownership tables now have service coverage, but recording-contribution ledgers still exist only at schema level
- migration `32 -> 33` intentionally collapses multiple work links down to one governing work per track by keeping the primary or first link
- `RightsRecords` still permits mixed-scope grant rows, so the rights layer is not fully narrowed yet

## Workers Used And Workers Closed

Workers used for the Phase 2 planning kickoff before implementation:

- `Laplace`
- `Turing`
- `Hume`

Workers closed:

- `Laplace`
- `Turing`
- `Hume`

No new workers were required for this implementation slice.

## QA/QC Summary From Central Oversight

This slice is coherent with the v3 product direction.

- `Work` is now materially closer to being the governing parent because `Track` rows can store that governance directly
- the app no longer depends exclusively on a many-to-many join to know a track’s parent work
- the explicit ownership/contribution schema has started without prematurely dragging UI into the same pass
- ownership separation now exists in services for work and recording control instead of remaining purely aspirational schema
- current read-side consumers remain stable because `WorkTrackLinks` is still synchronized for now

This is the correct boundary for the first Phase 2 landing. The next slices should build on this foundation rather than reopening the schema.

## Exact Safe Pickup Instructions

Next safe pickup for Phase 2:

1. read this handoff and confirm schema target `33` is the new baseline
2. keep Phase 2 at schema/service level until explicit ownership and contribution services are in place
3. continue by adding service models and CRUD flows for `RecordingContributionEntries`
4. narrow `RightsRecords` validation so one grant row cannot silently span multiple entity scopes
5. only after those service seams are stable, begin moving read-side consumers from `WorkTrackLinks` toward direct `Tracks.work_id`
6. do not start Work Manager UI expansion or work-first creation UX in the same pickup unless the ownership and recording-contribution services are already stable

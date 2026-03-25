# V3 Workflow Revision Phase 4

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 4 is `in_progress`, with broader expansion intentionally paused until the completed Phase 3 single-entrypoint closeout is reconciled.

The current Phase 4 work now covers two connected read-side slices:

- operational inventory and diagnostics started trusting the v3 governing `Tracks.work_id` relationship
- search relationships, Work Manager read-side track membership, workflow readiness, and XML export now also move toward the same authority path
- generic exchange JSON/package exports now also prefer governed work metadata over stale track-side composition shadow fields

The pre-Phase-4 creation-flow consolidation is now completed and documented at [`v3-workflow-revision-phase-3-single-entrypoint-closeout.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-phase-3-single-entrypoint-closeout.md).

Album-governance boundaries remain anchored to the reconciled decision note at [`v3-workflow-revision-album-governance-decision-note.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md).

## Phase Goal

Keep `Catalog` strong as the operational inventory while reducing duplicated governance and identity logic.

## What Changed

- `CatalogReadService` now joins `Tracks.work_id` to `Works` and prefers the linked work ISWC in catalog row projections before falling back to track-level shadow ISWC.
- `QualityDashboardService` now evaluates work-link authority from the v3 governing field on `Tracks` instead of relying on `WorkTrackLinks` as the source of truth:
  - `track_missing_linked_work` now checks whether `Tracks.work_id` resolves to a real work row
  - `orphaned_work_recording_link` now checks whether any tracks point directly at the work through `Tracks.work_id`
- `RelationshipExplorerService` now resolves work-to-track and track-to-work relationships from direct `Tracks.work_id` authority first, while only using `WorkTrackLinks` as a compatibility fallback when a track does not yet carry a governing `work_id`.
- `WorkService` now reads work track counts, work detail `track_ids`, and `list_works(linked_track_id=...)` from the same direct governing relationship first, so `Work Manager` navigation no longer goes empty when `WorkTrackLinks` drifts.
- `RepertoireWorkflowService.readiness_snapshot("track", ...)` now treats a valid direct `Tracks.work_id` link as authoritative before falling back to shadow rows.
- `XMLExportService` now prefers authoritative work-level composition data when available:
  - `Works.iswc` overrides stale track-side `iswc`
  - `Works.registration_number` overrides stale track-side `buma_work_number`
- `ExchangeService.export_rows()` now applies the same governed-work authority to outward-facing catalog exchange payloads:
  - JSON export now prefers `Works.iswc` and `Works.registration_number`
  - ZIP package manifest export now prefers the same governed fields
  - composition-side names now resolve from work governance first:
    - author roles come from `WorkContributors`
    - publisher names come from `WorkOwnershipInterests` first, then work-level publisher contributors as a fallback
- This keeps catalog, search, work navigation, workflow readiness, and XML export aligned with the parent-governance model without turning the catalog itself into a second authoring surface.

## Source Of Truth Files And Surfaces

- `isrc_manager/catalog_workspace.py`
- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/quality/service.py`
- `isrc_manager/search/service.py`
- `isrc_manager/works/service.py`
- `isrc_manager/services/repertoire_status.py`
- `isrc_manager/services/exports.py`
- `isrc_manager/exchange/service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_json.py`
- `tests/exchange/test_exchange_package.py`
- `tests/test_work_and_party_services.py`
- `tests/test_repertoire_status_service.py`
- `tests/test_xml_export_service.py`

## Files Changed

- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/quality/service.py`
- `isrc_manager/search/service.py`
- `isrc_manager/works/service.py`
- `isrc_manager/services/repertoire_status.py`
- `isrc_manager/services/exports.py`
- `isrc_manager/exchange/service.py`
- `tests/exchange/_repertoire_exchange_support.py`
- `tests/exchange/_support.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/test_catalog_workflow_integration.py`
- `tests/exchange/test_exchange_json.py`
- `tests/exchange/test_exchange_package.py`
- `tests/test_work_and_party_services.py`
- `tests/test_repertoire_status_service.py`
- `tests/test_xml_export_service.py`

## Tests Added Or Updated

- Added catalog-read coverage proving the table projection prefers authoritative `Works.iswc` over a stale track-level copy when `Tracks.work_id` is present.
- Added quality coverage proving direct `Tracks.work_id` authority is enough even if `WorkTrackLinks` is missing, so quality does not falsely report:
  - `track_missing_linked_work`
  - `orphaned_work_recording_link`
- Added relationship-explorer integration coverage proving work-to-track and track-to-work navigation still resolves correctly after deleting the matching `WorkTrackLinks` row, as long as authoritative `Tracks.work_id` remains correct.
- Added Work Manager service coverage proving `fetch_work()`, `fetch_work_detail()`, and `list_works(linked_track_id=...)` still return the governed child track when the shadow row is removed.
- Added workflow-readiness coverage proving `readiness_snapshot("track", ...)` treats direct `Tracks.work_id` as sufficient authority even without the shadow link row.
- Added XML export coverage proving authoritative work metadata overrides stale track-side composition shadow fields when `Tracks.work_id` is present.
- Added exchange JSON export coverage proving exported row payloads prefer authoritative work `iswc`, work registration, and governed work-side creator/publisher names over stale track shadow fields.
- Added exchange ZIP-package coverage proving the package manifest applies the same governed metadata authority.
- Validation run:
  - `python3 -m unittest tests.test_work_and_party_services tests.test_repertoire_status_service`
  - `python3 -m unittest tests.test_catalog_workflow_integration tests.integration.test_global_search_relationships`
  - `python3 -m unittest tests.test_xml_export_service`
  - `python3 -m unittest tests.test_catalog_read_service tests.test_quality_service`
  - `python3 -m unittest tests.exchange.test_exchange_json tests.exchange.test_exchange_package`

## What Was Intentionally Deferred

- broader Phase 4 expansion until the reconciled album-governance guardrails are applied consistently
- broader Phase 4 read-side work in this specific turn while the creation-flow consolidation was being completed and validated
- broader catalog workspace projection changes
- bulk-edit and track-edit operational cleanup
- broader exchange import/update normalization around governed work metadata
- final legacy license deletion
- final shell cleanup

## Risks And Caveats

- Phase 4 must not recreate a second governance surface inside Catalog while cleaning up operational views
- catalog changes should consume the Phase 2 and Phase 3 model instead of inventing transitional duplicate fields
- `WorkTrackLinks` still exists as shadow compatibility in other services; this slice narrows read authority in catalog, quality, search, work navigation, workflow readiness, and XML export first, but does not delete that table or fully remove legacy read paths elsewhere
- `CatalogReadService` still projects track-side `buma_work_number` because the catalog table does not yet have a dedicated first-class work registration field in its row model
- exchange import/update flows still accept and persist track-side composition fields because this slice only changed outward-facing export authority
- album-related follow-up must respect the reconciled decision note:
  - the album dialog stays a release/batch-entry surface
  - fallback mode auto-creates governed work parents
  - no album batch save may silently mix governance modes

## Workers Used And Workers Closed

- Workers used:
  - `Dewey`
  - `Godel`
  - `Gibbs`
  - `Hegel`
- Workers closed:
  - `Dewey`
  - `Godel`
  - `Gibbs`
  - `Hegel`

## QA/QC Summary From Central Oversight

This is a valid Phase 4 start because it changes authority, not concept:

- `Catalog` still behaves as inventory and operational read surface
- `Work Manager` still owns governance and creation
- read-side catalog, quality, search relationships, work navigation, workflow readiness, and XML export now trust the direct governing `Tracks.work_id` relationship first, which matches the v3 architecture

Central Oversight check:

- good: inventory and diagnostics are starting to consume the parent-governance model
- good: no new creation surface was added to Catalog
- good: Work Manager and Global Search now agree with the governing work link even when the shadow table is stale
- next: continue with the remaining import/update and operational read paths that still treat track-side composition shadow fields as authoritative before attempting final legacy deletion

## Exact Safe Pickup Instructions

Next safe Phase 4 continuation:

1. read the masterplan, the completed Phase 3 handoff, the single-entrypoint closeout handoff, and [`v3-workflow-revision-album-governance-decision-note.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md) first
2. treat the single-entrypoint closeout and the album-governance note as active guardrails, not as optional background context
3. continue from `catalog_reads.py` and other read-only catalog/search/export surfaces before reshaping edit forms
4. continue with the remaining import/update and operational exchange paths that still privilege track-side composition shadow fields over authoritative work data
5. keep adding integration tests as authority moves from shadow structures to v3 authoritative data
6. defer final legacy-license deletion until the replacement read and operational paths are fully stable

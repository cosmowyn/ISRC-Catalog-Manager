# V3 Workflow Revision Phase 4

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 4 is `in_progress`, with broader expansion intentionally paused until the completed Phase 3 single-entrypoint closeout is reconciled.

This first Phase 4 slice starts the read-side authority cleanup so operational inventory and diagnostics consume the v3 work model instead of older shadow assumptions.

The pre-Phase-4 creation-flow consolidation is now completed and documented at [`v3-workflow-revision-phase-3-single-entrypoint-closeout.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-phase-3-single-entrypoint-closeout.md).

Album-governance boundaries remain anchored to the reconciled decision note at [`v3-workflow-revision-album-governance-decision-note.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md).

## Phase Goal

Keep `Catalog` strong as the operational inventory while reducing duplicated governance and identity logic.

## What Changed

- `CatalogReadService` now joins `Tracks.work_id` to `Works` and prefers the linked work ISWC in catalog row projections before falling back to track-level shadow ISWC.
- `QualityDashboardService` now evaluates work-link authority from the v3 governing field on `Tracks` instead of relying on `WorkTrackLinks` as the source of truth:
  - `track_missing_linked_work` now checks whether `Tracks.work_id` resolves to a real work row
  - `orphaned_work_recording_link` now checks whether any tracks point directly at the work through `Tracks.work_id`
- This keeps `Catalog` and quality diagnostics aligned with the parent-governance model without turning the catalog itself into a second authoring surface.

## Source Of Truth Files And Surfaces

- `isrc_manager/catalog_workspace.py`
- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/quality/service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/test_catalog_workflow_integration.py`

## Files Changed

- `isrc_manager/services/catalog_reads.py`
- `isrc_manager/quality/service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`

## Tests Added Or Updated

- Added catalog-read coverage proving the table projection prefers authoritative `Works.iswc` over a stale track-level copy when `Tracks.work_id` is present.
- Added quality coverage proving direct `Tracks.work_id` authority is enough even if `WorkTrackLinks` is missing, so quality does not falsely report:
  - `track_missing_linked_work`
  - `orphaned_work_recording_link`
- Validation run:
  - `python3 -m unittest tests.test_catalog_read_service tests.test_quality_service tests.test_catalog_workflow_integration`
  - `python3 -m unittest tests.app.test_app_shell_workspace_docks tests.app.test_app_shell_startup_core tests.test_quality_dialogs`

## What Was Intentionally Deferred

- broader Phase 4 expansion until the reconciled album-governance guardrails are applied consistently
- broader Phase 4 read-side work in this specific turn while the creation-flow consolidation was being completed and validated
- broader catalog workspace projection changes
- bulk-edit and track-edit operational cleanup
- search/export authority cleanup beyond the Phase 3 governance-routing closeout
- final legacy license deletion
- final shell cleanup

## Risks And Caveats

- Phase 4 must not recreate a second governance surface inside Catalog while cleaning up operational views
- catalog changes should consume the Phase 2 and Phase 3 model instead of inventing transitional duplicate fields
- `WorkTrackLinks` still exists as shadow compatibility in other services; this slice narrows read authority in catalog/quality first, but does not delete that table or fully remove legacy read paths elsewhere
- catalog rows still surface some track-side composition shadow fields such as `buma_work_number`; richer work-summary projection remains a later Phase 4 slice
- album-related follow-up must respect the reconciled decision note:
  - the album dialog stays a release/batch-entry surface
  - fallback mode auto-creates governed work parents
  - no album batch save may silently mix governance modes

## Workers Used And Workers Closed

None in this slice.

## QA/QC Summary From Central Oversight

This is a valid Phase 4 start because it changes authority, not concept:

- `Catalog` still behaves as inventory and operational read surface
- `Work Manager` still owns governance and creation
- read-side catalog and quality logic now trust the direct governing `Tracks.work_id` relationship first, which matches the v3 architecture

Central Oversight check:

- good: inventory and diagnostics are starting to consume the parent-governance model
- good: no new creation surface was added to Catalog
- next: continue replacing shadow/workaround read paths in catalog/search/export before attempting final legacy deletion

## Exact Safe Pickup Instructions

Next safe Phase 4 continuation:

1. read the masterplan, the completed Phase 3 handoff, the single-entrypoint closeout handoff, and [`v3-workflow-revision-album-governance-decision-note.md`](/Users/cosmowyn/Projects/ISRC%20code%20manager/Source/ISRC-Catalog-Manager/docs/implementation_handoffs/v3-workflow-revision-album-governance-decision-note.md) first
2. treat the single-entrypoint closeout and the album-governance note as active guardrails, not as optional background context
3. continue from `catalog_reads.py` and other read-only catalog/search/export surfaces before reshaping edit forms
4. replace remaining read paths that still privilege track-side composition shadow fields or `WorkTrackLinks` over direct `Tracks.work_id`
5. keep adding integration tests as authority moves from shadow structures to v3 authoritative data
6. defer final legacy-license deletion until the replacement read and operational paths are fully stable

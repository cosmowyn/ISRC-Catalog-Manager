# V3 Workflow Revision Phase 0

Current product version: `2.0.0`

Target product version: `3.0.0`

Date: 2026-03-25

## Status And Scope

Phase 0 is complete.

This pass stayed in architecture, continuity, and characterization scope.

It did not:

- rewrite runtime product flows
- alter schema targets
- change UI behavior
- remove legacy license codepaths
- start the v3 Party, Work, or Catalog cutovers

## Phase Goal

Define the repo-grounded v3 workflow architecture, reserve a pause-safe handoff chain for the remaining phases, and lock the current track-first and legacy-license baseline in tests before broad product reshaping begins.

## What Was Implemented In This Pass

- expanded the v3 masterplan into a repo-grounded `3.0.0` architecture handoff
- wrote the temporary Wave 1 planning checkpoint on the required v3 path
- created placeholder per-phase handoffs for Phases 1 through 5 so the project has explicit pickup paths
- added characterization tests that pin the current workflow reality before the v3 revision starts
- confirmed that the current app is still track-first, catalog-read centric on track tables, and directly dependent on legacy license tables in quality and exchange codepaths

## Source Of Truth Files And Surfaces

Primary code and docs reviewed or characterized for Phase 0:

- `ISRC_manager.py`
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
- `docs/implementation_handoffs/contract-template-placeholder-masterplan.md`
- `docs/implementation_handoffs/contract-template-placeholder-phase-0.md`
- `docs/implementation_handoffs/backlog-unified-implementation-strategy.md`

## Files Changed

- `docs/implementation_handoffs/v3-workflow-revision-masterplan.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-0.md`
- `docs/implementation_handoffs/v3-workflow-revision-planning-wave-1-checkpoint.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-1.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-3.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-5.md`
- `tests/test_track_service.py`
- `tests/test_catalog_read_service.py`
- `tests/test_quality_service.py`
- `tests/exchange/_support.py`
- `tests/exchange/test_exchange_package.py`

## Tests Added Or Updated

Characterization coverage added in this phase:

- `tests/test_track_service.py`
  - `test_create_track_does_not_require_works_table_or_rows`
  - confirms current track creation is independent of `Works` and succeeds in a track-first schema
- `tests/test_catalog_read_service.py`
  - `test_catalog_reads_prefer_current_tracks_and_albums_tables`
  - confirms current catalog reads still source album metadata from `Tracks` and `Albums`
- `tests/test_quality_service.py`
  - `test_scan_reports_orphaned_license_when_track_reference_is_broken`
  - confirms `QualityDashboardService` still reads `Licenses` directly
- `tests/exchange/_support.py`
  - `case_package_export_includes_legacy_license_files_column`
  - confirms export packaging still emits `license_files` from legacy license rows
- `tests/exchange/test_exchange_package.py`
  - wires the new package-export characterization into the test suite

## Validation Performed

Commands run during Phase 0 included:

- `git status --short --branch`
- targeted `rg` and `sed` inspection across workflow, schema, quality, exchange, work, party, and handoff surfaces
- `python3 -m unittest tests.test_track_service tests.test_catalog_read_service tests.test_quality_service tests.exchange.test_exchange_package`

Result:

- the targeted Phase 0 characterization suite passed

## What Was Intentionally Deferred

- Party-first identity cutover
- work-parent and track-child schema revision
- ownership and contribution model separation in runtime code
- Work Manager UI expansion
- track creation workflow rewrite
- Catalog operational cleanup against the future governance model
- legacy license removal
- old database compatibility strategy beyond honest documentation

## Risks And Caveats

- the current app still stores composition-adjacent fields on `Tracks`, which means later phases must move authority deliberately rather than assume it already lives on `Work`
- quality and exchange codepaths still read legacy license tables directly, so Phase 5 cleanup must replace those reads before removing the tables
- the current Phase 0 track-first test proves independence from `Works`, but later phases should add stronger full-schema governance tests as soon as the new parent-child flow lands
- the masterplan defines the future architecture; it does not mean the repo already behaves that way

## Worker List And Closures

Phase 0 implementation helpers used under central oversight:

- `Mill`
  - drafted the initial Phase 0 handoff set
  - closed after reconciliation
- `Herschel`
  - landed the initial characterization-test pass
  - closed after reconciliation
- `Newton`
  - performed doc-structure QA against the required handoff format
  - closed after reconciliation
- `Epicurus`
  - reviewed the cleanest characterization seams for the Phase 0 baseline
  - closed after reconciliation

Planning-note continuity:

- this implementation pass also consumed already reconciled planning-wave findings from the earlier v3 strategy step
- no helper-agent wave exceeded the 6-worker cap

## QA/QC Summary From Central Oversight

Central-oversight conclusions for Phase 0:

- the repo still behaves like a track-first system even though `Work`, `Party`, `Contract`, and `Rights` seams already exist
- `Catalog` is currently operating as a track-row inventory fed from `Tracks`, `Artists`, and `Albums`
- legacy license logic remains live in quality and exchange surfaces and must be removed as a planned architectural change, not as incidental cleanup
- the project now has a master architecture handoff, a planning checkpoint, and a reserved phase-by-phase continuation chain, which makes pauses safer and reduces architectural drift

## Exact Safe Pickup Instructions For Phase 1

Start Phase 1 with Party authority cutover only.

Do this next:

1. reread the masterplan and this Phase 0 handoff
2. inspect the current identity-bearing flows in work, party, contract, rights, and settings surfaces
3. convert the first targeted identity-bearing fields to Party-first selectors plus quick-create flows
4. add tests before broad UI expansion:
   - Party selector and quick-create behavior
   - owner identity resolution
   - work and contract binding behavior
5. keep scope bounded to identity authority; do not start the work-parent schema rewrite in the same phase

Do not do this in Phase 1:

- do not rewrite track creation yet
- do not remove license tables yet
- do not merge work ownership, recording ownership, and contributions into one stopgap abstraction
- do not keep adding new free-text identity fields while the Party cutover is in flight

## Handoff Paths Defined For Future Phases

- `docs/implementation_handoffs/v3-workflow-revision-phase-1.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-2.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-3.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-4.md`
- `docs/implementation_handoffs/v3-workflow-revision-phase-5.md`

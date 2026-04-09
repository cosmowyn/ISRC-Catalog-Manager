# Party Manager Artist Authority Fix

## Summary
Party Manager is now the authoritative source for artist identity across the app.

The old split was:

- Party Manager wrote `Parties` and `PartyArtistAliases`
- track creation and several selectors still read and wrote legacy `Artists` / `TrackArtists.artist_id`
- open selectors refreshed inconsistently and often only after manual combo repopulation

The result was the exact broken behavior reported:

- Party-created artists were invisible in Add Track and related selectors
- track-first artist entry appeared to work only because it dual-wrote into the legacy artist tables

## Root Cause
The defect was a combination of four problems:

1. Artist authority was split between `Parties` and legacy `Artists`.
2. Add Track and several read/query surfaces still loaded artist choices from legacy artist storage.
3. Track-first creation created or reused a Party, but also seeded legacy artist rows, masking the split-brain design.
4. Party mutations did not broadcast one shared refresh signal to open selectors and views.

## Previous Selector Sources
Before this fix:

- Add Track / Add Album base artist combos were populated from legacy catalog combo values, which still used `Artists`.
- Edit Track artist fields were seeded from text-only artist lookup values rather than Party-backed identity.
- Release editor artist suggestions mixed release text fields with non-authoritative sources.
- Work editor contributor selectors were Party-backed already, but did not auto-refresh when Party data changed elsewhere.
- Bulk audio attach artist override was free text and not Party-backed at all.
- Several catalog/search/export/read paths still joined `Artists` for track artist display.

## Canonical Authority Change
Artist identity now resolves from the Party model and Party service.

Implemented changes:

- schema target moved to `39`
- `Tracks.main_artist_id` was replaced by `Tracks.main_artist_party_id`
- `TrackArtists.artist_id` was replaced by `TrackArtists.party_id`
- fresh schemas no longer create the legacy `Artists` table
- migration `38 -> 39` backfills legacy track artist references into Party-backed references and drops `Artists`
- `PartyService` now exposes:
  - `list_artist_parties()`
  - `find_artist_party_id_by_name()`
  - `ensure_artist_party_by_name()`
- artist relevance is defined from Party data and Party-backed track usage, not from a second registry
- shared artist label helpers now use one rule: `artist_name -> display_name -> company_name -> legal_name`

## Track-First Creation Now Uses Party Authority
Typing a non-existing artist during track creation or track editing now goes through the Party authority path.

That flow now:

- resolves an existing artist Party when one already matches
- promotes a generic same-name Party into artist authority when appropriate
- creates a new artist Party when no Party exists
- persists the resulting Party id into `Tracks.main_artist_party_id` and `TrackArtists.party_id`

The legacy dual-write behavior to `Artists` is gone for current schemas.

## Selector Refresh and Propagation
Party mutations now emit a shared notifier through `party_authority_notifier().changed`.

Open artist-dependent surfaces now refresh from Party authority without reopening:

- main Add Track artist selectors
- Add Album track-row artist selectors
- Edit Track / bulk edit artist selectors
- Release editor artist selectors
- Work editor contributor Party selectors
- stored artist usage panes
- bulk audio attach artist override selector

The main app also refreshes Party-dependent views after authority changes, including combo sources, catalog table reads, workspace docks, and relevant manager panels.

## Read/Query Unification
Track artist display queries were moved off direct `Artists` joins onto Party-backed helpers.

Updated surfaces include:

- catalog reads
- exports
- search / relationship explorer
- quality service
- exchange service
- assets / rights / contracts dialog reference track labels

This makes Party edits and Party-backed track artist persistence show up consistently in downstream views.

## Tests Added and Updated
Added:

- `tests/database/test_schema_migrations_38_39.py`

Updated:

- `tests/database/_schema_support.py`
- `tests/test_governed_track_creation_service.py`
- `tests/test_work_and_party_services.py`
- `tests/test_repertoire_dialogs.py`
- `tests/app/_app_shell_support.py`
- `tests/app/test_app_shell_editor_surfaces.py`

Coverage added or tightened for:

- current-target schema uses Party-backed artist references
- legacy `38 -> 39` migration backfills track artist Parties and drops `Artists`
- track-first artist creation creates/reuses Party authority
- Party merge and usage summary include Party-backed track references
- release/work dialog Party refresh behavior
- Add Track immediate Party-first availability
- Add Track track-first artist creation and selector reuse
- live rename propagation into open Add Track selectors

Verified with:

- `python3 -m unittest tests.database.test_schema_current_target tests.database.test_schema_migrations_38_39 tests.test_governed_track_creation_service tests.test_work_and_party_services tests.test_repertoire_dialogs tests.app.test_app_shell_editor_surfaces`
- `python3 -m unittest tests.test_quality_service tests.integration.test_global_search_relationships`

## Risks and Caveats
- The codebase still keeps legacy-compatible fallbacks in some services and tests so older/manual schemas can still be exercised intentionally. Current runtime authority is Party-backed.
- The `38 -> 39` migration now fails fast if it encounters unresolved legacy additional-artist references, because silently dropping those credits would be worse than surfacing the data issue.
- Release `primary_artist` / `album_artist` remain stored as release text fields, but selector suggestions and canonicalization now come from Party authority.
- Generic same-name Parties may be promoted into the artist subset instead of creating a duplicate Party. That is intentional to avoid split identity.

## Final Statement
Party Manager is now the authoritative source for artist identity across the app. Party-first creation, track-first creation, selector population, and dependent artist-facing views all converge on the same Party-backed authority model.

# Album Art Master/Slave Reference Guard
Date: 2026-03-23

## Status And Scope

This handoff covers one coordinated patch set:

- album-art master/slave guarding in single-edit and bulk-edit flows
- backend validation that blocks slave-record artwork replacement
- tagged-audio export alignment for managed-file and database/blob audio
- ISRC embedding on export through the existing audio-tag writer, including WAV via the current WAVE/ID3 path

Important: "master/slave" here is editor-facing language layered on top of the existing shared-album-art model. It is not a schema migration and it does not introduce a persisted owner-track column.

## Source Of Truth

Use these files together:

- [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/tags/models.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/models.py)
- [`isrc_manager/tags/service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/service.py)
- [`tests/test_track_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_track_service.py)
- [`tests/test_tag_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_tag_service.py)
- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)

## Confirmed Current Behavior And Root Cause

Album art was already shared by album context:

- real album groups store effective album art on `Albums`
- if album-level art is empty, `TrackService` falls back to the first track in the album that still carries legacy track-level art
- there is no persisted master/slave flag and no stored owner-track id

The bug was an edit-surface integrity gap:

- non-master tracks could still surface a replace/upload affordance even when they only referenced shared art owned elsewhere
- backend album-art mutation paths did not reject those slave writes
- blob/database-backed shared art was harder to reason about because the editor only displayed a resolved file path, so stored blobs could look blank

Audio export had a parallel consistency gap:

- catalog tag data was already built centrally through `_catalog_tag_data_for_track(...)`
- `AudioTagService.write_tags(...)` already handled ISRC and already wrote WAV tags through the existing WAVE/ID3 branch
- the export action only accepted tracks whose `audio_file_path` resolved to a filesystem path, so database/blob audio was skipped even though the metadata and writer stack were already available

## Exact Guard Applied

Shared scaffolding introduced first:

- `AlbumArtEditState` in [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py)
- `TrackService.describe_album_art_edit_state(track_id, *, cursor=None)`

The helper derives edit ownership from existing state:

- `owner_scope == "track"`: the current track directly owns editable art
- `owner_scope == "album_track"`: the fallback owner is the first track in album order with legacy track-level art
- `owner_scope == "album"` and album group size is `1`: the current track is editable
- `owner_scope == "album"` and album group size is greater than `1`: the editor-facing master/edit-entry track is the lowest `Tracks.id` in `list_album_group_track_ids(...)`

Backend protection:

- `TrackService.set_media_path(..., "album_art", ...)` now blocks slave/reference replacement attempts
- `TrackService.convert_media_storage_mode(..., "album_art", ...)` now blocks the same slave/reference path
- `TrackService.clear_media(..., "album_art", ...)` remains intentionally group-wide and is not blocked
- the shared error message is:
  `Album art for this track is managed by Track #<id> "<title>". Edit that record to replace the shared image.`

UI protection:

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py) now keeps album-art browse/clear widgets on the dialog instance for assertions and state refresh
- single edit disables `Browse…` when the current record is a slave/reference record, but leaves `Clear` enabled
- bulk edit disables `Browse…` whenever any selected track is not directly editable under the current persisted ownership state
- both surfaces show a hint identifying the master/edit-entry track
- both surfaces now expose an `Open Master Record` action from that hint; when more than one owner is involved, the action presents a small chooser menu
- save-time validation re-checks the same rule before constructing an album-art write, so a programmatic field change cannot bypass the disabled button state

Blob visibility fix:

- album-art display now uses the resolved path when present
- otherwise it falls back to `"<filename> (stored in database)"`
- otherwise it shows `"Stored in database"`
- that same display path is used for bulk mixed-state comparison, so blob-backed shared art no longer appears blank in the editor

Single-edit propagation fix:

- the source track still writes shared album art through the normal `update_track(...)` path
- peer propagation no longer re-sends `album_art_source_path` / `clear_album_art` through `apply_album_metadata_to_tracks(...)`
- only actual album metadata fields propagate to peer tracks
- this avoids tripping the new backend guard on peer records while preserving the shared album-art outcome

Bulk-edit write fix:

- bulk edit still applies one album-art change request from the selected window
- repeated `album_art_source_path` writes are stripped from later payloads that target the same shared album group
- this keeps multi-selection updates deterministic when several selected rows belong to one shared album

## Audio Export Metadata Alignment

Shared scaffolding introduced:

- `TaggedAudioExportItem` in [`isrc_manager/tags/models.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/models.py)
- it carries `suggested_name`, `tag_data`, `source_suffix`, and exactly one source form: `source_path` or `source_bytes`

Authoritative export path:

- [`isrc_manager/tags/service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/service.py) now materializes the export copy first
- managed-file sources are copied with `shutil.copy2(...)`
- database/blob sources are written out from bytes
- tags are then written to the exported destination file, never to the original source

App-level alignment:

- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py) now builds `TaggedAudioExportItem` entries for both managed and database/blob audio
- source suffix prefers `snapshot.audio_file_filename`, then falls back to MIME-based extension derivation
- preview text now explicitly says: `Preview the catalog metadata that will be written into exported audio copies. The original stored audio stays untouched.`

ISRC behavior:

- no new tag schema was added in this pass
- export continues to use the existing `AudioTagData` field set
- ISRC remains part of that field set and is written on exported copies wherever the current tag writer supports it
- WAV export continues to carry ISRC through the repo's existing `AudioTagService.write_tags(...)` WAVE -> ID3 path

## Tests Added Or Updated

Track-service coverage in [`tests/test_track_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_track_service.py):

- direct track-art ownership state
- album-owned shared-art master/slave state
- legacy `album_track` fallback owner/slave state
- slave-record replace guard for `set_media_path(...)`
- slave-record convert guard for `convert_media_storage_mode(...)`
- regression that the master/edit-entry record can still replace shared art
- regression that clearing shared art restores direct upload ability under the existing shared-album model

Tagged-audio export coverage in [`tests/test_tag_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_tag_service.py):

- managed-file export copies get metadata written while the source remains unchanged
- byte-backed/database-like export copies get the same metadata written
- exported WAV files round-trip with ISRC
- existing progress and cancellation behavior remains covered

Editor/export surface coverage in [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py):

- single-edit slave dialog disables album-art browse and shows the master hint
- single-edit master dialog keeps album-art browse enabled
- bulk edit disables album-art browse when the selection includes a slave/reference record
- one end-to-end tagged-audio export run covers a managed WAV and a database-backed WAV

## Remaining Limits / Future Follow-Up

- The canonical master/edit-entry track for album-owned shared art is still derived, not persisted. Today it is the lowest track id in the album group.
- Clearing shared album art remains intentionally group-wide, even when triggered from a slave/reference dialog.
- The export alignment is limited to tagged-audio-copy export. XML, exchange, and package exports remain unchanged in this pass.
- The tag field set was intentionally not expanded beyond the current `AudioTagData` schema.

## Reference Appendix

- [`isrc_manager/services/tracks.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/services/tracks.py)
- [`ISRC_manager.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/ISRC_manager.py)
- [`isrc_manager/tags/models.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/models.py)
- [`isrc_manager/tags/service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/isrc_manager/tags/service.py)
- [`tests/test_track_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_track_service.py)
- [`tests/test_tag_service.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/test_tag_service.py)
- [`tests/app/_app_shell_support.py`](/Users/cosmowyn/Projects/ISRC code manager/Source/ISRC-Catalog-Manager/tests/app/_app_shell_support.py)
